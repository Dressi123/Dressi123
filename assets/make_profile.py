#!/usr/bin/env python3
"""Generate every image in the profile README, in both themes.

One source, two files per image: light and dark differ only by palette, and
hand-maintaining the pairs is how they drift apart. Run after editing:

    pip install fonttools brotli
    python3 assets/make_profile.py

Type: an SVG loaded through <img> cannot fetch web fonts, so each file carries
its own fonts as base64 WOFF2, subset to exactly the glyphs that file draws.
Fraunces for display, Instrument Sans for reading, JetBrains Mono for anything
typed. Layout measures text from the real advance widths, so chips and pills
fit their labels instead of guessing.

Motion is SMIL, which GitHub's image proxy passes through and every browser
plays inside an <img>. rsvg-convert ignores it (and the fonts), so check real
output in a browser.
"""
import base64
import io
import math
import re
from collections import defaultdict
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

HERE = Path(__file__).parent
SRC = HERE / "src"

FALLBACK = {
    "serif": "Georgia, 'Times New Roman', serif",
    "sans": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif",
    "mono": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
}
FACES = {
    "display": ("Fraunces-Display.ttf", "serif"),
    "title": ("Fraunces-Title.ttf", "serif"),
    "sans": ("InstrumentSans-Regular.ttf", "sans"),
    "sans-bold": ("InstrumentSans-SemiBold.ttf", "sans"),
    "mono": ("JetBrainsMono-Regular.ttf", "mono"),
    "mono-med": ("JetBrainsMono-Medium.ttf", "mono"),
}
_fonts = {}


def font(face):
    if face not in _fonts:
        _fonts[face] = TTFont(SRC / "fonts" / FACES[face][0])
    return _fonts[face]


def measure(text, face, size, ls=0.0):
    f = font(face)
    cmap, hmtx, upm = f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm
    adv = sum(hmtx[cmap.get(ord(ch), ".notdef")][0] for ch in text)
    return adv / upm * size + ls * max(0, len(text) - 1)


_subsets = {}


def woff2(face, chars):
    key = (face, "".join(sorted(chars)))
    if key not in _subsets:
        opts = subset.Options()
        opts.flavor = "woff2"
        opts.layout_features = ["kern", "liga", "calt"]
        opts.name_IDs = []
        opts.notdef_outline = True
        f = subset.load_font(str(SRC / "fonts" / FACES[face][0]), opts)
        sub = subset.Subsetter(opts)
        sub.populate(text="".join(chars) + " ")
        sub.subset(f)
        buf = io.BytesIO()
        subset.save_font(f, buf, opts)
        _subsets[key] = base64.b64encode(buf.getvalue()).decode()
    return _subsets[key]


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt(xs):
    """Pixel and opacity values: two decimals is sub-pixel already."""
    return ";".join(f"{x:.2f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in xs)


def fmt_t(xs):
    """keyTimes are fractions of the whole cycle, so they need real precision:
    at two decimals a 21.6 s loop snaps to 216 ms steps and typed characters
    arrive in clumps of four."""
    return ";".join(f"{x:.6f}" for x in xs)


class Doc:
    """An SVG under construction that remembers which glyphs each face drew."""

    def __init__(self, w, h, label):
        self.w, self.h, self.label = w, h, label
        self.parts = []
        self.used = defaultdict(set)

    def add(self, *s):
        self.parts.extend(s)

    def text(self, x, y, s, face, size, fill, anchor=None, ls=None, extra="", inner=None):
        self.used[face].update(s)
        a = f' text-anchor="{anchor}"' if anchor else ""
        l = f' letter-spacing="{ls}"' if ls else ""
        body = inner if inner is not None else esc(s)
        self.add(
            f'<text x="{x:.1f}" y="{y:.1f}" class="{face}" font-size="{size}" fill="{fill}"{a}{l} {extra}>'
            f"{body}</text>"
        )

    def render(self):
        css = []
        for face, chars in sorted(self.used.items()):
            fam = f"p-{face}"
            css.append(
                f"@font-face{{font-family:'{fam}';src:url(data:font/woff2;base64,{woff2(face, chars)}) format('woff2')}}"
                f".{face}{{font-family:'{fam}',{FALLBACK[FACES[face][1]]}}}"
            )
        return "\n".join([
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}" role="img" '
            f'aria-label="{esc(self.label)}">',
            f"<style>{''.join(css)}</style>",
            *self.parts,
            "</svg>",
        ])


def entrance(delay, dur=0.6, dist=6):
    """Settle into place once: a short rise, never a fade. Content is fully opaque
    in every frame, so a renderer whose animation clock is frozen (headless
    captures, some previewers) still shows the whole page, just a few pixels low."""
    total = delay + dur
    k = delay / total
    return (
        f'<animateTransform attributeName="transform" type="translate" dur="{total:.2f}s" fill="freeze" '
        f'keyTimes="0;{k:.3f};1" values="0 {dist};0 {dist};0 0" calcMode="spline" keySplines="0 0 1 1;0.2 0 0.2 1"/>'
    )


def png_uri(name):
    mime = "image/webp" if name.endswith(".webp") else "image/png"
    return f"data:{mime};base64," + base64.b64encode((SRC / name).read_bytes()).decode()


def webp_size(name):
    """Canvas size from an animated WebP's VP8X header (stored minus one, 24-bit LE)."""
    b = (SRC / name).read_bytes()
    assert b[12:16] == b"VP8X", f"{name} is not an extended WebP"
    return int.from_bytes(b[24:27], "little") + 1, int.from_bytes(b[27:30], "little") + 1


# Navy, teal and gold: the palette Marble and claude-pet already share.
DARK = dict(
    name="dark",
    bg0="#040915", bg1="#0B1531", dots="#1A2647", card="#0B1326", card2="#101B34",
    well="#0E1830", stroke="#1F2C48", head="#EFF3F9", body="#97A6BC", dim="#5F6F88",
    teal="#4ECDC4", gold="#F2BF4B", blue="#8EA7FF", coral="#FF6B6B",
    chip="#131E37", chip_text="#CAD5E4", sphere="#091530",
    title=("#F6F9FC", "#BDF1EC", "#4ECDC4"),
)
LIGHT = dict(
    name="light",
    bg0="#FDFBF6", bg1="#EAF0F7", dots="#D8DFEA", card="#FFFFFF", card2="#F7F9FC",
    well="#F2F5FA", stroke="#DFE5EE", head="#0B1430", body="#4F5F77", dim="#8494AA",
    teal="#0D9488", gold="#B7791F", blue="#2F5BD3", coral="#DC2626",
    chip="#F3F6FA", chip_text="#2D3B52", sphere="#E6EEF8",
    title=("#0B1430", "#123A5C", "#0D9488"),
)


# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------

ROLES = [
    "full-stack engineer",
    "building AI agents + MCP servers",
    "shipping native Swift apps",
    "teaching models to spot fraud",
]
ROLE_WINDOW = 5.4      # seconds each role owns, typing through clearing
HOLD_UNTIL = 3.7       # when backspacing starts, within the window
ROLE_FS = 23
PLACES = [
    (40, -100), (30, -85), (47, -120), (19, -99), (-10, -76), (-13, -72),
    (56, 10), (52, 0), (46, 2), (41, 13), (40, -4), (39, 35), (27, 30),
    (60, 18), (64, 26), (37, 23), (37, -122), (10, -84),
]


def typing_events():
    """(time, typed_chars, busy) for the whole cycle, busy meaning a key is moving."""
    events = [(0.0, 0, False)]
    for i, role in enumerate(ROLES):
        t = i * ROLE_WINDOW + 0.35
        for c in range(1, len(role) + 1):
            # an uneven, human cadence: a beat after spaces, quicker inside words
            t += 0.052 + 0.026 * ((c * 37) % 5) / 4 + (0.09 if role[c - 1] == " " else 0)
            events.append((t, (i, c), True))
        events.append((t + 0.02, (i, len(role)), False))
        t = i * ROLE_WINDOW + HOLD_UNTIL
        for c in range(len(role) - 1, -1, -1):
            t += 0.024
            events.append((t, (i, c), True))
        events.append((t + 0.02, (i, 0), False))
    return events


def hero(p):
    W, H = 1200, 420
    cx, cy, R = 934, 214, 142
    d = Doc(W, H, "Andreas Jack Christiansen: full-stack engineer building AI agents, MCP servers and native Swift apps")
    t0, t1, t2 = p["title"]
    d.add(
        "<defs>",
        f'<clipPath id="frame"><rect width="{W}" height="{H}" rx="18"/></clipPath>',
        f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{p["bg0"]}"/>'
        f'<stop offset="1" stop-color="{p["bg1"]}"/></linearGradient>',
        f'<linearGradient id="title" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{t0}"/>'
        f'<stop offset="0.55" stop-color="{t1}"/><stop offset="1" stop-color="{t2}"/></linearGradient>',
        f'<radialGradient id="glow" cx="{cx}" cy="{cy}" r="320" gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{p["teal"]}" stop-opacity="0.24"/>'
        f'<stop offset="1" stop-color="{p["teal"]}" stop-opacity="0"/></radialGradient>',
        f'<radialGradient id="warm" cx="80" cy="420" r="420" gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{p["gold"]}" stop-opacity="0.10"/>'
        f'<stop offset="1" stop-color="{p["gold"]}" stop-opacity="0"/></radialGradient>',
        f'<radialGradient id="sphere" cx="{cx - 55}" cy="{cy - 65}" r="{R * 1.5}" gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{p["card2"]}"/><stop offset="1" stop-color="{p["sphere"]}"/></radialGradient>',
        f'<pattern id="dots" width="26" height="26" patternUnits="userSpaceOnUse">'
        f'<circle cx="2" cy="2" r="1.1" fill="{p["dots"]}"/></pattern>',
        f'<clipPath id="globe"><circle cx="{cx}" cy="{cy}" r="{R}"/></clipPath>',
        '<linearGradient id="fade" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0.05" stop-color="#000"/><stop offset="0.6" stop-color="#fff"/></linearGradient>',
        f'<mask id="dotmask"><rect width="{W}" height="{H}" fill="url(#fade)"/></mask>',
        "</defs>",
        '<g clip-path="url(#frame)">',
        f'<rect width="{W}" height="{H}" fill="url(#bg)"/>',
        f'<rect width="{W}" height="{H}" fill="url(#dots)" mask="url(#dotmask)"/>',
        f'<rect width="{W}" height="{H}" fill="url(#glow)"/>',
        f'<rect width="{W}" height="{H}" fill="url(#warm)"/>',
    )

    def rise(delay, dist=14):
        return entrance(delay, 0.8, dist)

    x = 68
    d.add(f"<g>{rise(0.05, 8)}")
    d.text(x, 94, "~/dressi123 $ whoami", "mono", 15, p["dim"],
           inner=f'<tspan fill="{p["teal"]}">~/dressi123</tspan> <tspan fill="{p["gold"]}">$</tspan> whoami')
    d.add("</g>")
    for n, (y, line) in enumerate(((176, "Andreas Jack"), (252, "Christiansen"))):
        d.add(f"<g>{rise(0.18 + n * 0.12)}")
        d.text(x - 4, y, line, "display", 78, "url(#title)", ls=-1.5)
        d.add("</g>")

    # typing line
    ry = 314
    d.add(f"<g>{rise(0.45, 8)}")
    d.text(x, ry, "›", "mono-med", ROLE_FS, p["gold"])
    tx = x + 28
    adv = ROLE_FS * 0.6          # JetBrains Mono: 600/1000 units, exactly
    events = typing_events()
    total = ROLE_WINDOW * len(ROLES)
    for i, role in enumerate(ROLES):
        times, widths = [0.0], [len(role) * adv + 1 if i == 0 else 0.0]
        widths[0] = 0.0
        for t, state, _ in events[1:]:
            ri, c = state
            if ri == i:
                times.append(t)
                widths.append(c * adv + (0.5 if c else 0))
        times.append(total)
        widths.append(0.0)
        key = [t / total for t in times]
        d.add(
            f'<clipPath id="role{i}"><rect x="{tx}" y="{ry - 26}" height="36" '
            f'width="{len(role) * adv + 1 if i == 0 else 0:.1f}">'
            f'<animate attributeName="width" dur="{total}s" repeatCount="indefinite" calcMode="discrete" '
            f'keyTimes="{fmt_t(key)}" values="{fmt(widths)}"/></rect></clipPath>'
        )
        # Each role is also shown only during its own slot. The clip does the typing in a
        # browser, but some renderers (the GitHub mobile app) ignore clip-path and would
        # stack all four phrases on one line; there the static frame shows role 0 alone.
        start, end = i * ROLE_WINDOW / total, (i + 1) * ROLE_WINDOW / total
        if i == 0:
            show = f'keyTimes="0;{end:.6f}" values="visible;hidden"'
        elif i == len(ROLES) - 1:
            show = f'keyTimes="0;{start:.6f}" values="hidden;visible"'
        else:
            show = f'keyTimes="0;{start:.6f};{end:.6f}" values="hidden;visible;hidden"'
        d.text(tx, ry, role, "mono", ROLE_FS, p["head"],
               extra=f'clip-path="url(#role{i})" visibility="{"visible" if i == 0 else "hidden"}"',
               inner=f'{esc(role)}<animate attributeName="visibility" dur="{total}s" repeatCount="indefinite" '
                     f'calcMode="discrete" {show}/>')

    # cursor: follows the typed width, solid while keys move, blinking at rest
    ctimes, cx_, cop = [], [], []
    width = 0.0
    last = 0.0
    for t, state, busy in events:
        if not busy:
            # fill the idle stretch until the next event with a 0.53s blink
            nxt = next((e[0] for e in events if e[0] > t), total)
            s, on = t, True
            while s < nxt - 0.01:
                ctimes.append(s)
                cx_.append(tx + (state[1] * adv if state else 0) + 2)
                cop.append(1 if on else 0)
                s += 0.53
                on = not on
            continue
        ctimes.append(t)
        cx_.append(tx + state[1] * adv + 2)
        cop.append(1)
    ctimes.append(total)
    cx_.append(tx + 2)
    cop.append(1)
    key = [t / total for t in ctimes]
    d.add(
        f'<rect x="{tx + len(ROLES[0]) * adv + 2:.1f}" y="{ry - 20}" width="{adv * 0.55:.1f}" height="26" '
        f'rx="1.5" fill="{p["teal"]}">'
        f'<animate attributeName="x" dur="{total}s" repeatCount="indefinite" calcMode="discrete" '
        f'keyTimes="{fmt_t(key)}" values="{fmt(cx_)}"/>'
        f'<animate attributeName="opacity" dur="{total}s" repeatCount="indefinite" calcMode="discrete" '
        f'keyTimes="{fmt_t(key)}" values="{fmt(cop)}"/></rect>'
    )
    d.add("</g>")

    # meta row
    my = 370
    mx = x
    for n, (color, label) in enumerate([
        (p["teal"], "SWE Intern @ Handshake AI ’26"),
        (p["gold"], "MSc Computer Science @ USF"),
        (p["blue"], "San Francisco"),
    ]):
        d.add(f"<g>{rise(0.6 + n * 0.09, 6)}")
        d.add(f'<circle cx="{mx + 5}" cy="{my - 5.5}" r="4.5" fill="{color}"/>')
        d.text(mx + 18, my, label, "sans-bold", 16, p["body"])
        d.add("</g>")
        mx += 18 + measure(label, "sans-bold", 16) + 28

    # globe
    d.add(f"<g>{rise(0.3, 0)}")
    d.add(f'<circle cx="{cx}" cy="{cy}" r="{R}" fill="url(#sphere)"/>')
    d.add(f'<g clip-path="url(#globe)" fill="none" stroke="{p["teal"]}" stroke-width="1">')
    for lat in (-60, -30, 0, 30, 60):
        yy = cy - R * math.sin(math.radians(lat))
        rx = R * math.cos(math.radians(lat))
        d.add(f'<ellipse cx="{cx}" cy="{yy:.1f}" rx="{rx:.1f}" ry="{rx * 0.1:.1f}" stroke-opacity="0.22"/>')
    period, samples = 24.0, 48
    for k in range(6):
        phase = k * math.pi / 6
        vals = [R * abs(math.sin(2 * math.pi * s / samples + phase)) for s in range(samples + 1)]
        d.add(
            f'<ellipse cx="{cx}" cy="{cy}" rx="{vals[0]:.1f}" ry="{R}" stroke-opacity="0.3">'
            f'<animate attributeName="rx" dur="{period * 2}s" repeatCount="indefinite" values="{fmt(vals)}"/></ellipse>'
        )
    d.add("</g>")
    for lat, lon in PLACES:
        la = math.radians(lat)
        xs, op = [], []
        for s in range(samples + 1):
            a = math.radians(lon) + 2 * math.pi * s / samples
            xs.append(cx + R * math.cos(la) * math.sin(a))
            op.append(round(max(0.0, min(1.0, math.cos(la) * math.cos(a) * 3)), 2))
        d.add(
            f'<circle cx="{xs[0]:.1f}" cy="{cy - R * math.sin(la):.1f}" r="4" fill="{p["gold"]}" opacity="{op[0]}">'
            f'<animate attributeName="cx" dur="{period}s" repeatCount="indefinite" values="{fmt(xs)}"/>'
            f'<animate attributeName="opacity" dur="{period}s" repeatCount="indefinite" values="{fmt(op)}"/></circle>'
        )
    d.add(f'<circle cx="{cx}" cy="{cy}" r="{R}" fill="none" stroke="{p["teal"]}" stroke-opacity="0.55" stroke-width="1.5"/>')
    for n, (orx, ory, tilt, color, dur, rev) in enumerate([
        (212, 50, -16, p["blue"], 14, False), (186, 70, 22, p["gold"], 19, True),
    ]):
        sweep = 0 if rev else 1
        path = f"M {cx - orx} {cy} a {orx} {ory} 0 1 {sweep} {orx * 2} 0 a {orx} {ory} 0 1 {sweep} {-orx * 2} 0"
        d.add(
            f'<g transform="rotate({tilt} {cx} {cy})">'
            f'<path id="orbit{n}" d="{path}" fill="none" stroke="{color}" stroke-opacity="0.4" stroke-width="1.2" stroke-dasharray="3 7"/>'
            f'<circle r="13" fill="{color}" opacity="0.18"><animateMotion dur="{dur}s" repeatCount="indefinite"><mpath xlink:href="#orbit{n}"/></animateMotion></circle>'
            f'<circle r="6" fill="{color}"><animateMotion dur="{dur}s" repeatCount="indefinite"><mpath xlink:href="#orbit{n}"/></animateMotion></circle>'
            f"</g>"
        )
    d.add("</g>")

    for label, tx_, ty_, color, delay in [
        # TypeScript and Python lead; Swift is one of four, not the headline
        ("typescript", 762, 92, p["teal"], 0), ("python", 1094, 118, p["gold"], 1.3),
        ("agentic ai", 806, 386, p["blue"], 0.7), ("swift", 1102, 336, p["dim"], 2.1),
    ]:
        w = measure(label, "mono", 13) + 26
        d.add(
            f'<g><animateTransform attributeName="transform" type="translate" dur="6s" begin="-{delay}s" '
            f'repeatCount="indefinite" values="0 0;0 -7;0 0" calcMode="spline" keySplines="0.45 0 0.55 1;0.45 0 0.55 1"/>'
            f'<rect x="{tx_ - w / 2:.1f}" y="{ty_ - 15}" width="{w:.1f}" height="28" rx="14" fill="{p["card"]}" '
            f'fill-opacity="0.85" stroke="{color}" stroke-opacity="0.55"/>'
        )
        d.text(tx_, ty_ + 4.5, label, "mono", 13, color, anchor="middle")
        d.add("</g>")

    d.add("</g>")
    d.add(f'<rect x="0.75" y="0.75" width="{W - 1.5}" height="{H - 1.5}" rx="17.5" fill="none" stroke="{p["stroke"]}" stroke-width="1.5"/>')
    return d.render()


# ---------------------------------------------------------------------------
# Project cards
# ---------------------------------------------------------------------------

CARDS = [
    dict(slug="second-brain", kicker="CLAUDE CODE · MCP", title="second-brain-skill",
         lines=["Turns a folder of markdown into a memory",
                "Claude actually uses: session hooks write",
                "the notes, two MCP servers read them back."],
         chips=["Python", "MCP", "OAuth", "Vercel"], status=("view repo ↗", "teal"), art="graph", tone="teal"),
    dict(slug="marble", kicker="iOS · SWIFTUI", title="Marble",
         lines=["Travel memories on a 3D globe. On-device",
                "Vision matches your photos to each trip",
                "and weeds out near-duplicates."],
         chips=["Swift", "SwiftData", "MapKit", "Vision"], status=("coming soon", "gold"),
         art="marble.png", tone="gold"),
    dict(slug="claude-pet", kicker="macOS · APPKIT", title="claude-pet",
         lines=["A native desktop fox that watches Claude",
                "Code's hooks and acts it out: working,",
                "asking for approval, failing, asleep."],
         chips=["Swift", "AppKit", "Claude Code hooks"], status=("view repo ↗", "teal"),
         art="pet-demo.webp", tone="gold"),
    dict(slug="learning-companion", kicker="EDGE AI · CLOUDFLARE", title="AI Learning Companion",
         lines=["Upload a PDF, get summaries, flashcards",
                "and quizzes. Runs on Cloudflare's edge",
                "with Workers AI (Llama 3.3)."],
         chips=["TypeScript", "Workers AI", "Next.js", "R2"], status=("view repo ↗", "teal"),
         art="cards", tone="teal"),
    dict(slug="fakeout", kicker="ML COURSE PROJECT · PAPER", title="FakeOut",
         lines=["Can weak supervision catch rental scams?",
                "Not here: 165 hand labels (AUROC 0.82)",
                "beat Snorkel over 99K listings (0.45)."],
         chips=["Snorkel", "scikit-learn", "Zillow ZORI"], status=("view repo ↗", "teal"),
         art="hist", tone="coral"),
    dict(slug="ais-thesis", kicker="ML RESEARCH · THESIS", title="Ship Trajectories",
         lines=["A Transformer-GRU hybrid that rebuilds",
                "vessel routes from AIS pings to within",
                "2 km, trained on 16M+ records."],
         chips=["PyTorch", "Dask", "DDP", "FastDTW"], status=("read paper ↗", "teal"), art="track", tone="blue"),
]


def art_block(d, p, kind, tone, x, y, w, h):
    mx, my = x + w / 2, y + h / 2
    d.add(
        f'<defs><radialGradient id="artglow" cx="{mx}" cy="{my}" r="{w * 0.75}" gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{p[tone]}" stop-opacity="0.16"/>'
        f'<stop offset="1" stop-color="{p[tone]}" stop-opacity="0"/></radialGradient>'
        f'<pattern id="artdots" width="14" height="14" patternUnits="userSpaceOnUse" x="{x}" y="{y}">'
        f'<circle cx="7" cy="7" r="0.9" fill="{p["dots"]}"/></pattern></defs>',
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{p["well"]}"/>',
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="url(#artdots)" opacity="0.7"/>',
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="url(#artglow)" stroke="{p["stroke"]}"/>',
    )
    if kind == "marble.png":
        d.add(
            f'<clipPath id="icon"><circle cx="{mx}" cy="{my}" r="67"/></clipPath>',
            f'<g clip-path="url(#icon)"><image x="{mx - 72}" y="{my - 72}" width="144" height="144" xlink:href="{png_uri(kind)}"/></g>',
            f'<circle cx="{mx}" cy="{my}" r="67" fill="none" stroke="{p["gold"]}" stroke-opacity="0.5" stroke-width="1.5" '
            f'stroke-dasharray="4 6"><animateTransform attributeName="transform" type="rotate" dur="30s" '
            f'repeatCount="indefinite" values="0 {mx} {my};360 {mx} {my}"/></circle>',
            f'<circle cx="{mx}" cy="{my - 67}" r="4" fill="{p["gold"]}"><animateTransform attributeName="transform" '
            f'type="rotate" dur="9s" repeatCount="indefinite" values="0 {mx} {my};360 {mx} {my}"/></circle>',
        )
    elif kind == "pet-demo.webp":
        # the repo's own demo, cropped and encoded at 1.5x (sharp on retina, half the
        # bytes of 2x once both themes embed it); it animates itself, so no bob
        iw, ih = webp_size(kind)
        dw, dh = iw / 1.5, ih / 1.5
        d.add(
            f'<ellipse cx="{mx}" cy="{my + dh / 2 - 4:.1f}" rx="{dw * 0.3:.1f}" ry="6" fill="#000" opacity="0.2"/>',
            f'<image x="{mx - dw / 2:.1f}" y="{my - dh / 2:.1f}" width="{dw:.1f}" height="{dh:.1f}" '
            f'xlink:href="{png_uri(kind)}"/>',
        )
    elif kind == "graph":
        nodes = [(mx, my, 13, p["teal"]), (mx - 48, my - 50, 7, p["blue"]), (mx + 46, my - 44, 8, p["gold"]),
                 (mx - 52, my + 40, 8, p["gold"]), (mx + 50, my + 48, 7, p["blue"]), (mx + 6, my - 82, 5, p["teal"]),
                 (mx - 6, my + 84, 5, p["teal"]), (mx + 72, my + 2, 5, p["teal"])]
        for nx, ny, _, _ in nodes[1:]:
            d.add(f'<line x1="{mx}" y1="{my}" x2="{nx}" y2="{ny}" stroke="{p["teal"]}" stroke-opacity="0.35" stroke-width="1.4"/>')
        for a, b in ((1, 5), (2, 7), (3, 6), (4, 7), (2, 5)):
            d.add(f'<line x1="{nodes[a][0]}" y1="{nodes[a][1]}" x2="{nodes[b][0]}" y2="{nodes[b][1]}" '
                  f'stroke="{p["blue"]}" stroke-opacity="0.25" stroke-width="1.2"/>')
        for n, (a, dur) in enumerate(((2, 2.2), (3, 2.9), (4, 2.5))):
            tx_, ty_ = nodes[a][0], nodes[a][1]
            d.add(
                f'<circle cx="{mx}" cy="{my}" r="3.2" fill="{p["gold"]}" opacity="0">'
                f'<animate attributeName="cx" dur="{dur}s" begin="{n * 0.7}s" repeatCount="indefinite" values="{mx};{tx_}"/>'
                f'<animate attributeName="cy" dur="{dur}s" begin="{n * 0.7}s" repeatCount="indefinite" values="{my};{ty_}"/>'
                f'<animate attributeName="opacity" dur="{dur}s" begin="{n * 0.7}s" repeatCount="indefinite" values="0;1;0"/></circle>'
            )
        for nx, ny, r, c in nodes:
            d.add(f'<circle cx="{nx}" cy="{ny}" r="{r}" fill="{c}"/>')
        d.add(
            f'<circle cx="{mx}" cy="{my}" r="13" fill="none" stroke="{p["teal"]}">'
            f'<animate attributeName="r" dur="2.2s" repeatCount="indefinite" values="13;32"/>'
            f'<animate attributeName="opacity" dur="2.2s" repeatCount="indefinite" values="0.7;0"/></circle>'
        )
    elif kind == "cards":
        for i, (dx, dy, rot, c) in enumerate(((-16, 10, -9, p["blue"]), (12, 4, 6, p["gold"]), (0, -6, 0, p["teal"]))):
            swing = ""
            if i < 2:
                swing = (f'<animateTransform attributeName="transform" type="rotate" dur="5s" repeatCount="indefinite" '
                         f'values="{rot} {mx} {my};{rot * 1.4} {mx} {my};{rot} {mx} {my}" calcMode="spline" '
                         f'keySplines="0.45 0 0.55 1;0.45 0 0.55 1"/>')
            d.add(f'<g transform="rotate({rot} {mx} {my})">{swing}<rect x="{mx - 52 + dx}" y="{my - 64 + dy}" '
                  f'width="104" height="128" rx="10" fill="{p["card"]}" stroke="{c}" stroke-width="1.6"/>')
            if i == 2:
                d.text(mx, my - 30, "Q · 3/10", "mono", 11, p["teal"], anchor="middle")
                for j, lw in enumerate((70, 58, 64)):
                    d.add(f'<rect x="{mx - 35}" y="{my - 12 + j * 14}" width="{lw}" height="5" rx="2.5" fill="{p["dim"]}" opacity="0.6"/>')
                d.add(f'<rect x="{mx - 35}" y="{my + 38}" width="70" height="14" rx="7" fill="{p["teal"]}" opacity="0.9">'
                      f'<animate attributeName="opacity" dur="1.8s" repeatCount="indefinite" values="0.35;0.95;0.35"/></rect>')
            d.add("</g>")
    elif kind == "hist":
        heights = [14, 26, 44, 70, 92, 80, 58, 38, 22, 12]
        bw, base = 11, my + 58
        x0 = mx - len(heights) * (bw + 3) / 2 + 8
        for i, hh in enumerate(heights):
            d.add(f'<rect x="{x0 + i * (bw + 3):.1f}" y="{base - hh}" width="{bw}" height="{hh}" rx="2" fill="{p["teal"]}" opacity="0.75">'
                  f'<animate attributeName="height" values="0;{hh}" dur="0.9s" begin="{0.1 + i * 0.05:.2f}s" fill="freeze" calcMode="spline" keySplines="0.2 0 0.2 1"/>'
                  f'<animate attributeName="y" values="{base};{base - hh}" dur="0.9s" begin="{0.1 + i * 0.05:.2f}s" fill="freeze" calcMode="spline" keySplines="0.2 0 0.2 1"/></rect>')
        ox = x0 - 24
        d.add(f'<rect x="{ox:.1f}" y="{base - 30}" width="{bw}" height="30" rx="2" fill="{p["coral"]}"/>')
        d.add(f'<circle cx="{ox + bw / 2:.1f}" cy="{base - 45}" r="9" fill="none" stroke="{p["coral"]}" stroke-width="1.6">'
              f'<animate attributeName="r" dur="1.6s" repeatCount="indefinite" values="8;13;8"/>'
              f'<animate attributeName="opacity" dur="1.6s" repeatCount="indefinite" values="1;0.3;1"/></circle>')
        d.text(ox + bw / 2, base - 40.5, "!", "sans-bold", 12, p["coral"], anchor="middle")
        d.add(f'<line x1="{x0 - 34:.1f}" y1="{base + 1}" x2="{mx + 80}" y2="{base + 1}" stroke="{p["dim"]}" stroke-opacity="0.6"/>')
        d.text(mx, base + 23, "$ / sqft vs ZORI", "mono", 10.5, p["dim"], anchor="middle")
    elif kind == "track":
        # a coastline, sparse AIS pings with a gap, and the model's route through them
        d.add(f'<path d="M {x + w - 58} {y} C {x + w - 30} {y + 50}, {x + w - 70} {y + 90}, {x + w - 40} {y + 130} '
              f'S {x + w - 20} {y + 200}, {x + w - 50} {y + h} L {x + w} {y + h} L {x + w} {y} Z" '
              f'fill="{p["blue"]}" fill-opacity="0.10" stroke="{p["blue"]}" stroke-opacity="0.35"/>')
        for gy in range(1, 4):
            d.add(f'<line x1="{x + 12}" y1="{y + gy * h / 4:.0f}" x2="{x + w - 12}" y2="{y + gy * h / 4:.0f}" '
                  f'stroke="{p["dim"]}" stroke-opacity="0.18" stroke-dasharray="1 5"/>')

        def bez(t, pts):
            (x0, y0), (x1, y1), (x2, y2), (x3, y3) = pts
            u = 1 - t
            return (u ** 3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3 * x3,
                    u ** 3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3 * y3)

        ctrl = [(x + 26, y + h - 30), (x + 40, y + 70), (x + 150, y + 190), (x + 118, y + 34)]
        route = f"M {ctrl[0][0]} {ctrl[0][1]} C {ctrl[1][0]} {ctrl[1][1]}, {ctrl[2][0]} {ctrl[2][1]}, {ctrl[3][0]} {ctrl[3][1]}"
        d.add(f'<path d="{route}" fill="none" stroke="{p["teal"]}" stroke-width="6" stroke-opacity="0.12" stroke-linecap="round"/>',
              f'<path d="{route}" fill="none" stroke="{p["teal"]}" stroke-width="2.2" stroke-linecap="round" '
              f'stroke-dasharray="300" stroke-dashoffset="0"><animate attributeName="stroke-dashoffset" dur="5s" '
              f'repeatCount="indefinite" keyTimes="0;0.6;1" values="300;0;0" calcMode="spline" '
              f'keySplines="0.3 0 0.2 1;0 0 1 1"/></path>')
        # the real pings: noisy, and missing a stretch in the middle the model fills in
        for t in (0.0, 0.07, 0.15, 0.22, 0.3, 0.64, 0.72, 0.8, 0.9, 1.0):
            px, py = bez(t, ctrl)
            jx, jy = 5 * math.sin(t * 41), 5 * math.cos(t * 29)
            d.add(f'<circle cx="{px + jx:.1f}" cy="{py + jy:.1f}" r="3" fill="{p["gold"]}"/>')
        # label the missing stretch from below, in open water, clear of the route
        gx, gy_ = bez(0.47, ctrl)
        d.add(f'<line x1="{gx + 4:.1f}" y1="{gy_ + 6:.1f}" x2="{gx + 4:.1f}" y2="{gy_ + 16:.1f}" stroke="{p["dim"]}" stroke-opacity="0.6"/>')
        d.text(gx + 4, gy_ + 28, "no signal", "mono", 10, p["dim"], anchor="middle")
        samples = [bez(s / 40, ctrl) for s in range(41)]
        sx0, sy0 = samples[0]
        d.add(f'<circle cx="{sx0:.1f}" cy="{sy0:.1f}" r="5.5" fill="{p["card"]}" stroke="{p["teal"]}" stroke-width="2.2">'
              f'<animate attributeName="cx" dur="5s" repeatCount="indefinite" keyTimes="{fmt_t([min(1, s / 40 * 0.6) for s in range(41)] + [1])}" '
              f'values="{fmt([pt[0] for pt in samples] + [samples[-1][0]])}"/>'
              f'<animate attributeName="cy" dur="5s" repeatCount="indefinite" keyTimes="{fmt_t([min(1, s / 40 * 0.6) for s in range(41)] + [1])}" '
              f'values="{fmt([pt[1] for pt in samples] + [samples[-1][1]])}"/></circle>')
        d.text(x + 14, y + 22, "±2 km", "mono", 10, p["teal"])


# Transparent space under each card. The README wraps all cards in one paragraph
# (so phones can stack them), which leaves no paragraph margin between rows.
CARD_GAP = 18


def card(p, spec):
    W, H = 600, 270
    d = Doc(W, H + CARD_GAP, f'{spec["title"]}: {" ".join(spec["lines"])}')
    tone = p[spec["tone"]]
    d.add(
        f'<defs><linearGradient id="cardbg" x1="0" y1="0" x2="0.4" y2="1"><stop offset="0" stop-color="{p["card2"]}"/>'
        f'<stop offset="1" stop-color="{p["card"]}"/></linearGradient>'
        f'<linearGradient id="edge" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{tone}" stop-opacity="0"/>'
        f'<stop offset="0.5" stop-color="{tone}" stop-opacity="0.8"/><stop offset="1" stop-color="{tone}" stop-opacity="0"/></linearGradient></defs>',
        f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="18" fill="url(#cardbg)" stroke="{p["stroke"]}" stroke-width="1.5"/>',
        f'<rect x="120" y="1" width="{W - 240}" height="1.5" fill="url(#edge)"/>',
    )
    art_block(d, p, spec["art"], spec["tone"], 20, 20, 190, H - 40)

    x = 238
    d.text(x, 53, spec["kicker"], "mono", 11, p["dim"], ls=1.6)
    status, st = spec["status"]
    color = p[st]
    sw = measure(status, "mono", 11) + 30
    sx = W - 22 - sw
    d.add(
        f'<rect x="{sx:.1f}" y="36" width="{sw:.1f}" height="23" rx="11.5" fill="{color}" fill-opacity="0.12" stroke="{color}" stroke-opacity="0.45"/>',
        f'<circle cx="{sx + 12.5:.1f}" cy="47.5" r="3.2" fill="{color}"><animate attributeName="opacity" dur="2s" '
        f'repeatCount="indefinite" values="1;0.35;1"/></circle>',
    )
    d.text(sx + 21, 51.5, status, "mono", 11, color)
    d.text(x - 1, 96, spec["title"], "title", 30, p["head"], ls=-0.4)
    for i, line in enumerate(spec["lines"]):
        d.text(x, 130 + i * 23, line, "sans", 15.5, p["body"])
    chip_x = x
    for chip in spec["chips"]:
        w = measure(chip, "mono", 11.5) + 22
        d.add(f'<rect x="{chip_x:.1f}" y="211" width="{w:.1f}" height="27" rx="7" fill="{p["chip"]}" stroke="{p["stroke"]}"/>')
        d.text(chip_x + 11, 228.5, chip, "mono", 11.5, p["chip_text"])
        chip_x += w + 8
    assert chip_x < W - 14, f"chips overflow on {spec['slug']}"
    return d.render()


# ---------------------------------------------------------------------------
# Journey timeline
# ---------------------------------------------------------------------------

# (when, kind, title, two lines of detail): kind picks the colour, school or work
JOURNEY = [
    ("2022", "school", "Aalborg University", ["B.Sc. Software Engineering", "Denmark · 2022–2025"]),
    ("2024", "work", "CEGO", ["Software Engineer, Frontend", "latency cut 44% at 9K+ users"]),
    ("2025", "school", "University of San Francisco", ["M.S. Computer Science, AI", "4.0 GPA · Dean's Scholar"]),
    ("2026", "work", "Handshake AI", ["Software Engineer Intern", "shipped LLM-judge evals"]),
    ("NOW", "now", "SnapLogic × USF", ["building an MCP server", "for the SLIM platform"]),
]


def journey(p):
    W, H = 1200, 256
    x0, x1, y = 110, 1090, 104
    d = Doc(W, H, "Journey: " + "; ".join(f"{yr} {t}, {s[0]}" for yr, _, t, s in JOURNEY))
    d.add(
        f'<defs><linearGradient id="rail" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{p["blue"]}"/>'
        f'<stop offset="0.5" stop-color="{p["teal"]}"/><stop offset="1" stop-color="{p["gold"]}"/></linearGradient>'
        f'<linearGradient id="cardbg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{p["card2"]}"/>'
        f'<stop offset="1" stop-color="{p["card"]}"/></linearGradient></defs>',
        f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="18" fill="url(#cardbg)" stroke="{p["stroke"]}" stroke-width="1.5"/>',
        f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="{p["stroke"]}" stroke-width="3" stroke-linecap="round"/>',
        f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="url(#rail)" stroke-width="3" stroke-linecap="round" '
        f'stroke-dasharray="{x1 - x0}" stroke-dashoffset="0"><animate attributeName="stroke-dashoffset" dur="2.6s" '
        f'values="{x1 - x0};0" calcMode="spline" keySplines="0.3 0 0.2 1" fill="freeze"/></line>',
    )
    step = (x1 - x0) / (len(JOURNEY) - 1)
    colors = {"school": p["blue"], "work": p["teal"], "now": p["gold"]}
    labels = {"school": "EDU", "work": "WORK", "now": "LIVE"}
    for i, (year, kind, title, sub) in enumerate(JOURNEY):
        nx, c = x0 + i * step, colors[kind]
        d.add(f"<g>{entrance(0.2 + i * 0.52, 0.6, 8)}")
        tag = labels[kind]
        yw = measure(year, "mono-med", 14, 1)
        tw = measure(tag, "mono", 9.5, 1) + 12
        gx = nx - (yw + 8 + tw) / 2
        d.text(gx, y - 30, year, "mono-med", 14, c, ls=1)
        d.add(f'<rect x="{gx + yw + 8:.1f}" y="{y - 43}" width="{tw:.1f}" height="17" rx="8.5" fill="{c}" '
              f'fill-opacity="0.12" stroke="{c}" stroke-opacity="0.4"/>')
        d.text(gx + yw + 8 + tw / 2, y - 31, tag, "mono", 9.5, c, anchor="middle", ls=1)
        d.add(f'<circle cx="{nx}" cy="{y}" r="11" fill="{p["card"]}" stroke="{c}" stroke-width="2.5"/>',
              f'<circle cx="{nx}" cy="{y}" r="5" fill="{c}"/>')
        if i == len(JOURNEY) - 1:
            d.add(f'<circle cx="{nx}" cy="{y}" r="11" fill="none" stroke="{c}"><animate attributeName="r" dur="2s" '
                  f'repeatCount="indefinite" values="11;26"/><animate attributeName="opacity" dur="2s" repeatCount="indefinite" values="0.8;0"/></circle>')
        d.text(nx, y + 52, title, "title", 19, p["head"], anchor="middle")
        for j, line in enumerate(sub):
            d.text(nx, y + 78 + j * 21, line, "sans", 14, p["body"], anchor="middle")
        d.add("</g>")
    return d.render()


# ---------------------------------------------------------------------------
# Toolbox
# ---------------------------------------------------------------------------

# (label, simple-icons slug or None, colour key or hex for dark, hex for light)
TOOLBOX = [
    ("Languages", [
        ("TypeScript", "typescript", "#3178C6", "#3178C6"), ("Python", "python", "#FFD43B", "#3776AB"),
        ("JavaScript", "javascript", "#F7DF1E", "#B59A00"), ("Java", "openjdk", "gold", "gold"),
        ("Go", "go", "#00ADD8", "#0089A7"), ("Swift", "swift", "#F05138", "#F05138"),
    ]),
    ("AI & data", [
        ("Claude API", "anthropic", "#D97757", "#C15F3C"), ("LangChain", "langchain", "head", "head"),
        ("MCP", "modelcontextprotocol", "head", "head"), ("PyTorch", "pytorch", "#EE4C2C", "#EE4C2C"),
        ("pandas", "pandas", "blue", "blue"), ("scikit-learn", "scikitlearn", "#F7931E", "#E07C0A"),
    ]),
    ("Apps & services", [
        ("Next.js", "nextdotjs", "head", "head"), ("React", "react", "#61DAFB", "#0891B2"),
        ("Vue.js", "vuedotjs", "#4FC08D", "#3F9E6F"), ("Node.js", "nodedotjs", "#5FA04E", "#4C8A3D"),
        ("tRPC", "trpc", "#398CCB", "#2A6FA3"), ("Temporal", "temporal", "head", "head"),
        ("PostgreSQL", "postgresql", "#7FB3F5", "#336791"),
    ]),
    ("Cloud & ops", [
        ("Cloudflare Workers", "cloudflare", "#F38020", "#E36B0A"), ("Vercel", "vercel", "head", "head"),
        ("AWS", None, "gold", "gold"), ("Docker", "docker", "#2496ED", "#1D7FC9"),
        ("GitHub Actions", "githubactions", "#2088FF", "#1F6FD1"), ("Datadog", "datadog", "#A87DDC", "#632CA6"),
    ]),
]


def icon_path(slug):
    return re.search(r'd="([^"]+)"', (SRC / "icons" / f"{slug}.svg").read_text()).group(1)


def toolbox(p):
    W, row_h, top = 1200, 64, 30
    H = top * 2 + row_h * len(TOOLBOX) - 8
    d = Doc(W, H, "Toolbox: " + "; ".join(f'{g}: {", ".join(i[0] for i in items)}' for g, items in TOOLBOX))
    d.add(
        f'<defs><linearGradient id="cardbg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{p["card2"]}"/>'
        f'<stop offset="1" stop-color="{p["card"]}"/></linearGradient></defs>',
        f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="18" fill="url(#cardbg)" stroke="{p["stroke"]}" stroke-width="1.5"/>',
    )
    n = 0
    for r, (group, items) in enumerate(TOOLBOX):
        y = top + r * row_h
        if r:
            d.add(f'<line x1="36" y1="{y - 8}" x2="{W - 36}" y2="{y - 8}" stroke="{p["stroke"]}" stroke-dasharray="2 5"/>')
        d.text(40, y + 29, group.upper(), "mono", 11.5, p["dim"], ls=1.6)
        x = 236
        for label, slug, dark, light in items:
            key = dark if p["name"] == "dark" else light
            color = p.get(key, key)
            w = 14 + 18 + 9 + measure(label, "sans-bold", 14.5) + 16
            d.add(f"<g>{entrance(0.1 + n * 0.035)}")
            d.add(f'<rect x="{x:.1f}" y="{y + 4}" width="{w:.1f}" height="40" rx="11" fill="{p["chip"]}" stroke="{p["stroke"]}"/>')
            if slug:
                d.add(f'<path transform="translate({x + 14:.1f} {y + 15}) scale(0.75)" d="{icon_path(slug)}" fill="{color}"/>')
            else:
                d.add(f'<rect x="{x + 17:.1f}" y="{y + 18}" width="12" height="12" rx="3" fill="none" stroke="{color}" stroke-width="2"/>'
                      f'<circle cx="{x + 23:.1f}" cy="{y + 24}" r="2" fill="{color}"/>')
            d.text(x + 41, y + 29, label, "sans-bold", 14.5, p["chip_text"])
            d.add("</g>")
            x += w + 10
            n += 1
        assert x < W - 30, f"toolbox row {group} overflows"
    return d.render()


# ---------------------------------------------------------------------------
# Section headers
# ---------------------------------------------------------------------------

def header(p, label, index, W=1200):
    """A section heading. Phones get W=520: every README image is drawn at the
    column's width, so a narrower canvas is what makes the same 31px label bigger."""
    H = 66
    d = Doc(W, H, label)
    d.text(4, 44, f"{index:02d}", "mono-med", 15, p["gold"])
    d.text(38, 46, label, "title", 31, p["head"], ls=-0.4)
    lx = 38 + measure(label, "title", 31, -0.4) + 22
    d.add(
        f'<line x1="{lx:.0f}" y1="35" x2="{W - 14}" y2="35" stroke="{p["stroke"]}" stroke-width="1.5"/>',
        f'<circle cx="{W - 8}" cy="35" r="4" fill="{p["teal"]}"><animate attributeName="opacity" dur="2.4s" '
        f'repeatCount="indefinite" values="1;0.3;1"/></circle>',
    )
    return d.render()


HEADERS = [("now", "Right now"), ("work", "Featured work"), ("journey", "How I got here"), ("toolbox", "Toolbox")]


def main():
    # Placeholders for the responsive card grid. A <picture> can swap its image by
    # screen width but not its width attribute, so each card appears twice and the
    # copy not meant for this screen shows one of these instead:
    #   blank-wide: under width="49%" it collapses to a sliver instead of a square
    #   blank-dot:  with no width attribute it takes one pixel
    (HERE / "blank-wide.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 1" width="600" height="1"/>\n')
    (HERE / "blank-dot.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1" width="1" height="1"/>\n')
    for p in (DARK, LIGHT):
        t = p["name"]
        (HERE / f"hero-{t}.svg").write_text(hero(p))
        (HERE / f"journey-{t}.svg").write_text(journey(p))
        (HERE / f"toolbox-{t}.svg").write_text(toolbox(p))
        for spec in CARDS:
            (HERE / f"card-{spec['slug']}-{t}.svg").write_text(card(p, spec))
        for i, (slug, label) in enumerate(HEADERS, 1):
            (HERE / f"h-{slug}-{t}.svg").write_text(header(p, label, i))
            (HERE / f"h-{slug}-{t}-phone.svg").write_text(header(p, label, i, W=520))
    files = sorted(HERE.glob("*.svg"))
    print(f"wrote {len(files)} svgs, {sum(f.stat().st_size for f in files) // 1024} KB")


if __name__ == "__main__":
    main()
