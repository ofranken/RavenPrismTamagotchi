"""
Procedural pixel-art raven, modelled on the fat round Raven plush:
a round black ball body, grey beak, grey three-toed feet, red cheek patch.

Everything here is pure Python. A frame is a CANVAS_W x CANVAS_H grid of palette
keys (or None for transparent). `frame_to_rgba` turns it into bytes for Qt or PIL.

Note on colour: Raven Prism is an additive waveguide display, so pure black is
invisible. The "black" raven is drawn in deep indigo with a lavender rim so it
reads as a dark, glossy raven while still being visible on the glasses.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

CANVAS_W = 64
CANVAS_H = 64
GROUND_Y = 60  # row the feet stand on

PALETTE: dict[str, tuple[int, int, int]] = {
    # body (glossy raven indigo, light from top-left)
    "O": (96, 100, 156),  # outline / rim
    "D": (22, 22, 36),  # deep shadow
    "B": (34, 35, 56),  # base
    "M": (50, 52, 84),  # mid
    "H": (80, 84, 134),  # highlight
    "S": (150, 156, 214),  # specular sheen
    # wing
    "w": (28, 28, 46),
    "v": (66, 70, 112),  # feather edges
    # beak & feet (grey felt)
    "g": (150, 154, 164),
    "G": (196, 200, 210),
    "q": (104, 108, 118),
    # cheek patch
    "r": (214, 64, 48),
    "R": (246, 112, 88),
    # eyes
    "K": (8, 8, 14),
    "W": (255, 255, 255),
    "L": (200, 205, 255),  # eyelid
    "X": (235, 235, 245),  # dead / dizzy eyes
    # particles
    "Y": (255, 214, 64),
    "y": (255, 246, 176),
    "P": (255, 72, 110),
    "p": (255, 176, 196),
    "Z": (170, 210, 255),
}

BAYER4 = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)

Grid = list[list[Optional[str]]]


def new_grid(w: int = CANVAS_W, h: int = CANVAS_H) -> Grid:
    return [[None] * w for _ in range(h)]


def stamp(grid: Grid, art: list[str], x: int, y: int, mirror: bool = False) -> None:
    """Draw a small ASCII sprite ('.' or ' ' = transparent) at (x, y)."""
    h = len(grid)
    w = len(grid[0])
    for j, row in enumerate(art):
        if mirror:
            row = row[::-1]
        for i, ch in enumerate(row):
            if ch in ". ":
                continue
            px, py = x + i, y + j
            if 0 <= px < w and 0 <= py < h:
                grid[py][px] = ch


# --------------------------------------------------------------------------- sprites
EYES = {
    "open": [".KKK.", "KWWKK", "KWKKK", "KKKKK", ".KKK."],
    "blink": [".....", ".....", "KKKKK", ".....", "....."],
    "happy": [".....", ".KKK.", "K...K", ".....", "....."],  # ^ ^
    "closed": [".....", ".....", "K...K", ".KKK.", "....."],  # sleeping (u)
    "groggy": ["LLLLL", "LLLLL", "KKKKK", "KWKKK", ".KKK."],  # half-lidded
    "dizzy": ["XXXXX", "....X", "XXX.X", "X...X", "XXXXX"],  # spiral
    "dead": ["X...X", ".X.X.", "..X..", ".X.X.", "X...X"],
}

STAR_BIG = ["..Y..", ".YYY.", "YYyYY", ".YYY.", "..Y.."]
STAR_SMALL = [".Y.", "YyY", ".Y."]
HEART = [".PP.PP.", "PpPPPPP", "PPPPPPP", ".PPPPP.", "..PPP..", "...P..."]
HEART_SMALL = ["P.P", "PPP", ".P."]
ZZZ = ["ZZZZZ", "...Z.", "..Z..", ".Z...", "ZZZZZ"]
ZZZ_SMALL = ["ZZZZ", "..Z.", ".Z..", "ZZZZ"]

# chunky felt feet, facing left; bottom row sits on GROUND_Y (top row hides under the body)
FOOT = ["..qq.", "..qq.", ".gGGg", "gGggg", "g.g.g"]
FOOT_UP = ["..qq.", ".gGGg", "gGggg", "g.g.g", "....."]  # lifted one row (walking)


# --------------------------------------------------------------------------- pose
@dataclass
class Pose:
    eyes: str = "open"
    hop: int = 0  # logical px the whole bird is lifted
    squash: int = 0  # +1 = squashed (landing), -1 = stretched (take-off)
    wing: float = 25.0  # degrees from straight down, positive = toward the back
    wing_len: float = 13.0
    lean: int = 0  # -1..1, shears the upper body
    feet: str = "stand"  # stand | walk_a | walk_b | tuck
    mirror: bool = False  # True = facing right
    upside_down: bool = False  # dead
    beak_open: bool = False
    far_wing: Optional[float] = None  # draw the far wing tip too (flapping / dragging)
    stars: Optional[float] = None  # orbit phase in radians, None = no stars
    hearts: list[tuple[float, float, bool]] = field(default_factory=list)  # (x, y, small)
    zs: list[tuple[float, float, bool]] = field(default_factory=list)


# body geometry (facing left)
CX = 32
BODY_RX = 17
BODY_RY = 16


@lru_cache(maxsize=16)
def _body_layer(rx: int, ry: int, light_from_below: bool = False) -> tuple[tuple[Optional[str], ...], ...]:
    """Shaded, outlined body ball; rows/cols relative to a (2*rx+3) x (2*ry+3) box."""
    w, h = 2 * rx + 3, 2 * ry + 3
    cx, cy = rx + 1, ry + 1
    inside = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            dx = (x - cx + 0.5) / (rx + 0.3)
            dy = (y - cy + 0.5) / (ry + 0.3)
            # pear shape: a touch narrower at the top, like the plush
            if dy < 0:
                dx *= 1.0 + 0.10 * (-dy)
            inside[y][x] = dx * dx + dy * dy <= 1.0
    lx, ly, lz = -0.5, (0.62 if light_from_below else -0.62), 0.6
    n = math.sqrt(lx * lx + ly * ly + lz * lz)
    lx, ly, lz = lx / n, ly / n, lz / n
    rows: list[list[Optional[str]]] = [[None] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if inside[y][x]:
                nx = (x - cx + 0.5) / rx
                ny = (y - cy + 0.5) / ry
                nz = math.sqrt(max(0.0, 1.0 - nx * nx - ny * ny))
                lam = nx * lx + ny * ly + nz * lz  # -1..1
                t = (lam + 0.35) / 1.3 + (BAYER4[y % 4][x % 4] / 16.0 - 0.5) * 0.22
                if t > 0.96:
                    c = "S"
                elif t > 0.80:
                    c = "H"
                elif t > 0.58:
                    c = "M"
                elif t > 0.26:
                    c = "B"
                else:
                    c = "D"
                rows[y][x] = c
            else:
                for ddx, ddy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    xx, yy = x + ddx, y + ddy
                    if 0 <= xx < w and 0 <= yy < h and inside[yy][xx]:
                        rows[y][x] = "O"
                        break
    # a few plush "fur" flecks
    for (fx, fy) in ((cx - 6, cy + 4), (cx + 3, cy + 8), (cx - 2, cy + 10), (cx + 8, cy + 2), (cx - 9, cy + 9)):
        if 0 <= fy < h and 0 <= fx < w and rows[fy][fx] in ("B", "D"):
            rows[fy][fx] = "M"
    return tuple(tuple(r) for r in rows)


def _draw_wing(grid: Grid, pivot: tuple[float, float], angle_deg: float, length: float, width: float, far: bool = False) -> None:
    """Teardrop wing hanging from `pivot`, rotated `angle_deg` from straight down toward +x."""
    a = math.radians(angle_deg)
    ax, ay = math.sin(a), math.cos(a)  # unit axis along the wing (down when a=0)
    bx, by = ay, -ax  # perpendicular
    h = len(grid)
    w = len(grid[0])
    mask: dict[tuple[int, int], str] = {}
    x0 = int(pivot[0] - length - width) - 1
    x1 = int(pivot[0] + length + width) + 2
    y0 = int(pivot[1] - length - width) - 1
    y1 = int(pivot[1] + length + width) + 2
    for y in range(max(0, y0), min(h, y1, GROUND_Y + 1)):  # wings drag flat on the ground
        for x in range(max(0, x0), min(w, x1)):
            px, py = x + 0.5 - pivot[0], y + 0.5 - pivot[1]
            t = px * ax + py * ay  # along
            s = px * bx + py * by  # across
            if t < -1 or t > length:
                continue
            u = t / length
            half = width * (1.0 - u) ** 0.7 * min(1.0, (t + 1.5) / 3.0)
            if abs(s) <= half:
                # feather bands near the trailing edge
                band = int(t) % 3 == 2 and s * (1 if not far else -1) > 0
                mask[(x, y)] = "v" if band or u > 0.82 else ("D" if far else "w")
    for (x, y), c in mask.items():
        grid[y][x] = c
    # outline
    for (x, y) in list(mask):
        for ddx, ddy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            xx, yy = x + ddx, y + ddy
            if (xx, yy) not in mask and 0 <= xx < w and 0 <= yy < h:
                if grid[yy][xx] is None or grid[yy][xx] in "BDMHS":
                    grid[yy][xx] = "O"


def raven_layer(pose: Pose) -> Grid:
    """The raven itself (no particles), facing left, positioned on the ground."""
    g = new_grid()
    rx = BODY_RX + (1 if pose.squash > 0 else 0) - (1 if pose.squash < 0 else 0)
    ry = BODY_RY - (1 if pose.squash > 0 else 0) + (1 if pose.squash < 0 else 0)
    feet_h = 3
    bottom = GROUND_Y - feet_h - pose.hop  # last body row
    cy = bottom - ry
    top = cy - ry - 1
    left = CX - rx - 1

    # far wing (behind the body), peeks out on the left/front side
    if pose.far_wing is not None:
        _draw_wing(g, (CX - rx * 0.25, cy - ry * 0.15), -pose.far_wing, pose.wing_len * 0.85, 4.0, far=True)

    # feet first so the body hides the top of the legs
    foot_y = GROUND_Y - 4 - pose.hop
    fa, fb = FOOT, FOOT
    if pose.feet == "walk_a":
        fa = FOOT_UP
    elif pose.feet == "walk_b":
        fb = FOOT_UP
    if pose.feet != "tuck":
        stamp(g, fa, CX - 9, foot_y)
        stamp(g, fb, CX + 1, foot_y)

    # when dead the layer is flipped afterwards, so light it from below to keep it lit from above
    body = _body_layer(rx, ry, pose.upside_down)
    for j, row in enumerate(body):
        for i, c in enumerate(row):
            if c is None:
                continue
            x, y = left + i, top + j
            if 0 <= x < CANVAS_W and 0 <= y < CANVAS_H:
                if c == "O" and g[y][x] is not None:
                    continue  # keep far wing visible through the rim
                g[y][x] = c

    # beak: wedge pointing left from the face
    by = cy - int(ry * 0.32)
    bx = CX - rx + 1  # where the beak meets the face
    beak = [
        "......OOOO",
        "....OOGGGG",
        "..OOgGGGgg",
        "OOgggggggg",
        ".OOqqqgggg",
        "...OOOqqqq",
        "......OOOO",
    ] if not pose.beak_open else [
        "......OOOO",
        "....OOGGGG",
        "..OOgGGGgg",
        ".OOOOOOOOg",
        "...OKKKKKK",
        ".OOqqqqqqq",
        "...OOOOOOO",
    ]
    stamp(g, beak, bx - 8, by - 3)

    # eye + cheek
    ex = CX - int(rx * 0.42)
    ey = cy - int(ry * 0.52)
    stamp(g, EYES.get(pose.eyes, EYES["open"]), ex - 2, ey - 1)
    stamp(g, ["...rR", "..rrR", ".rrrR", "rrr.."], ex + 3, ey + 5)

    # near wing (on top)
    _draw_wing(g, (CX + rx * 0.42, cy - ry * 0.22), pose.wing, pose.wing_len, 5.5)

    # lean: shear upper body rows
    if pose.lean:
        for y in range(CANVAS_H):
            k = 0
            if y < cy - ry * 0.3:
                k = pose.lean
            if y < cy - ry * 0.75:
                k = pose.lean * 2
            if k:
                row = g[y]
                g[y] = row[-k:] + row[:-k]  # rotate right for k > 0, left for k < 0

    if pose.upside_down:
        # on its back, feet in the air, resting on the ground
        flipped = g[::-1]
        # find lowest occupied row after flip and drop it onto the ground
        lowest = max((y for y, r in enumerate(flipped) if any(c is not None for c in r)), default=CANVAS_H - 1)
        shift = GROUND_Y + 1 - lowest
        g = new_grid()
        for y, r in enumerate(flipped):
            ny = y + shift
            if 0 <= ny < CANVAS_H:
                g[ny] = list(r)
    if pose.mirror:
        g = [row[::-1] for row in g]
    return g


def head_center(pose: Pose) -> tuple[float, float]:
    ry = BODY_RY
    cy = GROUND_Y - 3 - pose.hop - ry
    x = CX - 4
    if pose.mirror:
        x = CANVAS_W - 1 - x
    return x, cy - ry * 0.75


def compose(pose: Pose) -> Grid:
    g = raven_layer(pose)
    if pose.stars is not None:
        hx, hy = head_center(pose)
        back: list[tuple[int, int, list[str]]] = []
        front: list[tuple[int, int, list[str]]] = []
        for k in range(3):
            a = pose.stars + k * 2 * math.pi / 3
            sx = hx + math.cos(a) * 15
            sy = hy - 5 + math.sin(a) * 4
            art = STAR_BIG if math.sin(a) > -0.3 else STAR_SMALL
            off = len(art) // 2
            (front if math.sin(a) > 0 else back).append((int(round(sx)) - off, int(round(sy)) - off, art))
        # back stars only where nothing is drawn yet
        for x, y, art in back:
            for j, row in enumerate(art):
                for i, ch in enumerate(row):
                    px, py = x + i, y + j
                    if ch != "." and 0 <= px < CANVAS_W and 0 <= py < CANVAS_H and g[py][px] is None:
                        g[py][px] = ch
        for x, y, art in front:
            stamp(g, art, x, y)
    for (x, y, small) in pose.hearts:
        art = HEART_SMALL if small else HEART
        stamp(g, art, int(round(x)) - len(art[0]) // 2, int(round(y)))
    for (x, y, small) in pose.zs:
        art = ZZZ_SMALL if small else ZZZ
        stamp(g, art, int(round(x)), int(round(y)))
    return g


def frame_to_rgba(grid: Grid) -> bytes:
    out = bytearray(len(grid) * len(grid[0]) * 4)
    i = 0
    for row in grid:
        for c in row:
            if c is not None:
                r, g, b = PALETTE[c]
                out[i] = r
                out[i + 1] = g
                out[i + 2] = b
                out[i + 3] = 255
            i += 4
    return bytes(out)


def frame_to_bgra(grid: Grid) -> bytes:
    """Byte order for QImage.Format_ARGB32 on little-endian machines."""
    out = bytearray(len(grid) * len(grid[0]) * 4)
    i = 0
    for row in grid:
        for c in row:
            if c is not None:
                r, g, b = PALETTE[c]
                out[i] = b
                out[i + 1] = g
                out[i + 2] = r
                out[i + 3] = 255
            i += 4
    return bytes(out)


# --------------------------------------------------------------------------- HUD icons (8x8)
ICONS = {
    "health": [".PP.PP..", "PpPPPPP.", "PPPPPPP.", ".PPPPP..", "..PPP...", "...P....", "........", "........"],
    "food": ["....q...", "...q....", ".rrrr...", "rRrrrr..", "rrrrrr..", "rrrrrr..", ".rrrr...", "........"],  # berry
    "energy": ["....YY..", "...YY...", "..YY....", ".YYYYY..", "...YY...", "..YY....", ".YY.....", "........"],  # bolt
    "play": ["...gg...", "..gGGg..", ".gGggqg.", ".ggggqg.", "..gqqg..", "...gg...", "...q....", "..qqq..."],  # footprint/ball
}
