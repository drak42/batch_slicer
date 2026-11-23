"""Draw BatchSlicer's retro banner: G-code rain, a green-screen console and a print in progress.

Writes one self-contained SVG (1280x640, GitHub's social-preview size).
Deterministic: the same seed gives the same picture. To make the PNG the
README uses, render the SVG in a browser, for example:

    python3 docs/images/make_banner.py docs/images/banner.svg
    google-chrome --headless=new --hide-scrollbars --window-size=1280,640 \
        --screenshot=docs/images/banner.png docs/images/banner.svg
"""

import math
import random
import sys
from xml.sax.saxutils import escape

W, H = 1280, 640
rng = random.Random(42)
out: list[str] = []
add = out.append

TOKENS = ["G1", "G0", "X", "Y", "Z", "E", "F", "M104", "M140", "T0", "T1", ";", "0", "1", "2", "3",
          "4", "5", "6", "7", "8", "9", ".", "G28", "M190", "G92"]

add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
    'font-family="DejaVu Sans Mono, Menlo, Consolas, monospace">')
add("<title>BatchSlicer</title>")
add("""<defs>
  <radialGradient id="vignette" cx="50%" cy="50%" r="75%">
    <stop offset="55%" stop-color="#000" stop-opacity="0"/>
    <stop offset="100%" stop-color="#000" stop-opacity="0.85"/>
  </radialGradient>
  <linearGradient id="screen" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#03140a"/>
    <stop offset="1" stop-color="#010804"/>
  </linearGradient>
  <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
    <feGaussianBlur stdDeviation="2.2" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <filter id="bigglow" x="-30%" y="-60%" width="160%" height="220%">
    <feGaussianBlur stdDeviation="7" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse">
    <rect width="4" height="2" fill="#000" fill-opacity="0.28"/>
  </pattern>
  <filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="28"/></filter>
  <clipPath id="crt"><rect x="70" y="150" width="640" height="400" rx="26"/></clipPath>
</defs>""")
add(f'<rect width="{W}" height="{H}" fill="#000"/>')

# --- G-code rain: columns of falling tokens, bright at the head, fading up the trail ---
add('<g font-size="15">')
col_w = 22
for col in range(W // col_w + 1):
    x = col * col_w + 4
    head = rng.uniform(-100, H + 200)
    length = rng.randint(6, 26)
    for i in range(length):
        y = head - i * 18
        if y < -20 or y > H + 20:
            continue
        fade = 1 - i / length
        if i == 0:
            colour, opacity = "#b8ffcf", 0.75
        else:
            colour, opacity = "#00ff66", 0.08 + 0.42 * fade ** 1.6
        token = rng.choice(TOKENS)
        if len(token) > 2:
            token = token[: rng.choice((1, 2))]
        add(f'<text x="{x}" y="{y:.0f}" fill="{colour}" fill-opacity="{opacity:.2f}">{escape(token)}</text>')
add("</g>")

# --- Dark backdrops so the title and the print stand clear of the rain ---
add('<ellipse cx="640" cy="98" rx="470" ry="70" fill="#000" fill-opacity="0.92" filter="url(#soft)"/>')
add('<ellipse cx="1000" cy="380" rx="230" ry="250" fill="#000" fill-opacity="0.9" filter="url(#soft)"/>')

# --- Title ---
add('<g filter="url(#bigglow)">')
add('<text x="640" y="92" text-anchor="middle" font-size="76" font-weight="bold" letter-spacing="10" '
    'fill="#39ff7a">BATCHSLICER</text>')
add("</g>")
add('<text x="640" y="126" text-anchor="middle" font-size="17" letter-spacing="5" fill="#7dffaa" '
    'fill-opacity="0.85">MODELS IN &#183; G-CODE OUT &#183; STRAIGHT TO THE PRINTER</text>')

# --- CRT console ---
add('<rect x="58" y="138" width="664" height="424" rx="34" fill="#0a0f0b" stroke="#1f3a28" stroke-width="3"/>')
add('<rect x="70" y="150" width="640" height="400" rx="26" fill="url(#screen)"/>')
lines = [
    ("$ batchslicer --input ~/kits/boat --plates \\", "#b6ffcc"),
    ("      --send k2plus --loaded-filaments", "#b6ffcc"),
    ("", None),
    ("Filaments loaded in k2plus:", "#39ff7a"),
    ("  CFS 1B dark blue PETG", "#39ff7a"),
    ("  external spool white PETG", "#39ff7a"),
    ("Slicing 3 model files ...", "#39ff7a"),
    ("  [1/1] boat/ (on plates) ... done (2.1s)", "#39ff7a"),
    ("Sliced 3 of 3 model files in 2.9s.", "#39ff7a"),
    ("  To print: 1h 29m, 30 g filament", "#39ff7a"),
    ("  [1/1] boat.gcode ... sent", "#39ff7a"),
    ("Sent 1 of 1 file to k2plus.", "#9dffbd"),
    ("$ █", "#b6ffcc"),
]
add('<g clip-path="url(#crt)" filter="url(#glow)" font-size="18">')
for n, (text, colour) in enumerate(lines):
    if colour:
        add(f'<text x="98" y="{196 + n * 26}" fill="{colour}" xml:space="preserve">{escape(text)}</text>')
add("</g>")
add('<rect x="70" y="150" width="640" height="400" rx="26" fill="url(#scan)"/>')
add('<rect x="70" y="150" width="640" height="400" rx="26" fill="none" stroke="#39ff7a" '
    'stroke-opacity="0.25" stroke-width="2"/>')
# glass reflection
add('<path d="M96 162 Q 380 150 690 170 L 690 196 Q 380 178 96 192 Z" fill="#fff" fill-opacity="0.035"/>')

# --- A part being printed: stacked wireframe layers of a twisted vase, under a glowing nozzle ---
cx, base_y = 1000, 520
layers = 34
done = 26  # layers already printed
add('<g filter="url(#glow)" fill="none">')
# build plate (isometric)
plate = [(cx - 190, base_y + 20), (cx, base_y - 50), (cx + 190, base_y + 20), (cx, base_y + 90)]
add('<polygon points="' + " ".join(f"{x},{y}" for x, y in plate) +
    '" stroke="#1d6b3c" stroke-width="2" fill="#03140a" fill-opacity="0.8"/>')
for i in range(1, 8):
    t = i / 8
    a = (plate[0][0] + (plate[1][0] - plate[0][0]) * t, plate[0][1] + (plate[1][1] - plate[0][1]) * t)
    b = (plate[3][0] + (plate[2][0] - plate[3][0]) * t, plate[3][1] + (plate[2][1] - plate[3][1]) * t)
    add(f'<line x1="{a[0]:.0f}" y1="{a[1]:.0f}" x2="{b[0]:.0f}" y2="{b[1]:.0f}" stroke="#0f3d22" stroke-width="1"/>')
    a = (plate[0][0] + (plate[3][0] - plate[0][0]) * t, plate[0][1] + (plate[3][1] - plate[0][1]) * t)
    b = (plate[1][0] + (plate[2][0] - plate[1][0]) * t, plate[1][1] + (plate[2][1] - plate[1][1]) * t)
    add(f'<line x1="{a[0]:.0f}" y1="{a[1]:.0f}" x2="{b[0]:.0f}" y2="{b[1]:.0f}" stroke="#0f3d22" stroke-width="1"/>')


def layer_points(k: int) -> list[tuple[float, float]]:
    """One layer: a rounded hexagon that widens then narrows and twists as it rises."""
    h = k / layers
    radius = 70 + 38 * math.sin(math.pi * h * 0.9) - 18 * h
    twist = h * 1.1
    pts = []
    for j in range(36):
        ang = 2 * math.pi * j / 36
        r = radius * (1 + 0.10 * math.cos(6 * (ang + twist)))
        x = cx + r * math.cos(ang)
        y = base_y + 0.42 * r * math.sin(ang) - k * 7.2
        pts.append((x, y))
    return pts


for k in range(done):
    pts = layer_points(k)
    shade = 0.35 + 0.65 * (k / done)
    colour = "#2fd8ff" if 9 <= k < 15 else "#39ff7a"  # a band in a second filament colour
    add('<polygon points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in pts) +
        f'" stroke="{colour}" stroke-opacity="{shade:.2f}" stroke-width="1.6"/>')
# the layer being printed now: drawn part solid, the rest still a dashed path
current = layer_points(done)
split = 22
add('<polyline points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in current[: split + 1]) +
    '" stroke="#d8ffe4" stroke-width="2.4"/>')
add('<polyline points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in current[split:] + current[:1]) +
    '" stroke="#39ff7a" stroke-opacity="0.35" stroke-width="1.4" stroke-dasharray="4 5"/>')
# a few layers still to come, as faint ghosts
for k in range(done + 1, layers):
    pts = layer_points(k)
    add('<polygon points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in pts) +
        '" stroke="#39ff7a" stroke-opacity="0.07" stroke-width="1"/>')
add("</g>")

# hotend with its glowing nozzle tip, at the end of the printed part of the layer
nx, ny = current[split]
add('<g filter="url(#glow)">')
add(f'<line x1="{nx:.0f}" y1="{ny - 70:.0f}" x2="{nx:.0f}" y2="{ny - 150:.0f}" stroke="#1d6b3c" stroke-width="6"/>')
add(f'<rect x="{nx - 30:.0f}" y="{ny - 70:.0f}" width="60" height="40" rx="5" fill="#04170c" '
    'stroke="#39ff7a" stroke-width="2"/>')
add(f'<rect x="{nx - 14:.0f}" y="{ny - 30:.0f}" width="28" height="12" fill="#04170c" stroke="#39ff7a" stroke-width="2"/>')
add(f'<polygon points="{nx - 9:.0f},{ny - 18:.0f} {nx + 9:.0f},{ny - 18:.0f} {nx:.0f},{ny - 4:.0f}" '
    'fill="#39ff7a"/>')
add("</g>")
add(f'<circle cx="{nx:.0f}" cy="{ny:.0f}" r="9" fill="#e8fff0" filter="url(#bigglow)"/>')
add(f'<text x="{nx + 40:.0f}" y="{ny - 44:.0f}" font-size="14" fill="#7dffaa" fill-opacity="0.9" '
    f'filter="url(#glow)">LAYER {done + 1}/{layers}</text>')

# --- Vignette and a whisper of overall scanlines ---
add(f'<rect width="{W}" height="{H}" fill="url(#vignette)"/>')
add(f'<rect width="{W}" height="{H}" fill="url(#scan)" fill-opacity="0.35"/>')
add("</svg>")

with open(sys.argv[1], "w", encoding="utf-8") as file:
    file.write("\n".join(out))
