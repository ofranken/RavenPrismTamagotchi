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
    # body: raven charcoal, with the purple-blue iridescence only in the highlights
    "O": (112, 110, 128),  # outline / rim (grey with a hint of violet)
    "D": (20, 20, 24),  # deep shadow
    "B": (34, 34, 40),  # base
    "M": (52, 51, 62),  # mid
    "H": (78, 72, 100),  # highlight (violet sheen)
    "S": (128, 116, 170),  # specular sheen
    # wing
    "w": (22, 22, 27),
    "v": (62, 60, 76),  # feather edges
    # beak & feet (grey, like the plush)
    "g": (128, 128, 134),
    "G": (172, 172, 178),
    "q": (86, 86, 92),
    # cheek patch
    "r": (214, 64, 48),
    "R": (246, 112, 88),
    # eyes
    "K": (8, 8, 14),
    "W": (255, 255, 255),
    "L": (150, 148, 168),  # eyelid
    "X": (235, 235, 245),  # dead / dizzy eyes
    # particles
    "Y": (255, 214, 64),
    "y": (255, 246, 176),
    "P": (255, 72, 110),
    "p": (255, 176, 196),
    "Z": (170, 210, 255),
    # seeds
    "s": (206, 186, 136),
    "t": (138, 116, 82),
    # tears
    "T": (120, 190, 255),
    # sunglasses
    "F": (186, 186, 198),
    # disco
    "1": (255, 255, 255),
    "2": (90, 240, 255),
    "3": (255, 90, 230),
    "4": (255, 230, 90),
    "5": (130, 130, 150),
    "6": (80, 80, 96),
    "j": (88, 80, 130),
    "k": (60, 54, 96),
    # damage flash (body tinted red)
    "d": (70, 16, 20),
    "b": (110, 24, 30),
    "m": (150, 36, 40),
    "h": (200, 60, 60),
    "o": (255, 110, 110),
}

FLASH = {"D": "d", "B": "b", "M": "m", "H": "h", "S": "h", "O": "o", "w": "d", "v": "m"}

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
    "pain": ["KK...", "..KK.", "....K", "..KK.", "KK..."],  # squeezed shut  >_<
}

SEED = ["ss.", "stt"]  # sunflower-ish seed
TEAR = ["T", "T"]
TEAR_BIG = [".T.", "TTT", ".T."]
# sunglasses (facing left): lenses are dark violet glass with a white glint, frames light so
# they show up on the additive display
SUNGLASSES = [
    "FFFFFFFFFF",
    "FjWjjjjFFF",
    "FWjjjjjF..",
    "FkkkkkkF..",
    ".FkkkkF...",
    "..FFFF....",
]
PAIN_BROW = ["LL....", "..LL..", "....L."]  # worried brow, inner end raised
FEATHER = [["..v", ".O.", "v.."], ["v..", ".O.", "..v"]]

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
    peck: bool = False  # head dipped down to eat
    flash: bool = False  # red damage flash
    seeds: list[tuple[float, float]] = field(default_factory=list)  # facing-left coords
    tears: list[tuple[float, float, bool]] = field(default_factory=list)  # facing-left coords
    feathers: list[tuple[float, float, int]] = field(default_factory=list)  # canvas coords
    sunglasses: bool = False
    disco: Optional[float] = None  # time (s) driving the disco ball spin, None = no party


# body geometry (facing left)
CX = 32
BODY_RX = 17
BODY_RY = 16


@lru_cache(maxsize=64)
def _body_layer(cx: int, cy: int, rx: int, ry: int, light_from_below: bool = False) -> tuple[tuple[Optional[str], ...], ...]:
    """Shaded, outlined raven body on a full canvas: round head + plump belly + wedge tail.

    Built as a union of shapes (not one ball) so there is a neck notch, a forehead and a tail.
    Each pixel is shaded with the normal of whichever shape it belongs to most.
    """
    hx, hy, hr = head_geometry(cx, cy, rx, ry)
    bx, by, brx, bry = cx + 1, cy + 3, rx, ry * 0.82
    # tail: wedge sticking out of the lower back, tilted slightly up
    tx0, ty0 = cx + rx * 0.72, cy + ry * 0.32
    tx1, ty1 = cx + rx + 7, cy + ry * 0.05
    tlen = math.hypot(tx1 - tx0, ty1 - ty0)
    tax, tay = (tx1 - tx0) / tlen, (ty1 - ty0) / tlen

    lx, ly, lz = -0.5, (0.62 if light_from_below else -0.62), 0.6
    n = math.sqrt(lx * lx + ly * ly + lz * lz)
    lx, ly, lz = lx / n, ly / n, lz / n

    kind = [[None] * CANVAS_W for _ in range(CANVAS_H)]
    norm: dict[tuple[int, int], tuple[float, float]] = {}
    for y in range(CANVAS_H):
        for x in range(CANVAS_W):
            px, py = x + 0.5, y + 0.5
            dh = ((px - hx) / hr) ** 2 + ((py - hy) / hr) ** 2
            db = ((px - bx) / brx) ** 2 + ((py - by) / bry) ** 2
            # tail
            t = (px - tx0) * tax + (py - ty0) * tay
            sdist = -(px - tx0) * tay + (py - ty0) * tax
            in_tail = 0 <= t <= tlen and abs(sdist) <= 3.6 * (1 - t / tlen) + 0.8
            if dh <= 1.0 or db <= 1.0:
                # blend head and belly normals near the neck so the head isn't a separate "helmet"
                wh, wb = math.exp(-5 * dh), math.exp(-5 * db)
                nhx, nhy = (px - hx) / hr, (py - hy) / hr
                nbx, nby = (px - bx) / brx, (py - by) / bry
                kind[y][x] = "body"
                norm[(x, y)] = ((wh * nhx + wb * nbx) / (wh + wb), (wh * nhy + wb * nby) / (wh + wb))
            elif in_tail:
                kind[y][x] = "tail"
                norm[(x, y)] = (0.6, sdist / 4.0)

    rows: list[list[Optional[str]]] = [[None] * CANVAS_W for _ in range(CANVAS_H)]
    for y in range(CANVAS_H):
        for x in range(CANVAS_W):
            k = kind[y][x]
            if k is not None:
                nx, ny = norm[(x, y)]
                nz = math.sqrt(max(0.0, 1.0 - nx * nx - ny * ny))
                lam = nx * lx + ny * ly + nz * lz
                t = (lam + 0.35) / 1.3 + (BAYER4[y % 4][x % 4] / 16.0 - 0.5) * 0.22
                if k == "tail":
                    t -= 0.15
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
                # tail feather lines
                if k == "tail" and (x + y) % 3 == 0:
                    c = "v"
                rows[y][x] = c
            else:
                for ddx, ddy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    xx, yy = x + ddx, y + ddy
                    if 0 <= xx < CANVAS_W and 0 <= yy < CANVAS_H and kind[yy][xx] is not None:
                        rows[y][x] = "O"
                        break
    # chest feather flecks (ravens have shaggy throat feathers)
    for (fx, fy) in ((hx + 1, hy + hr + 1), (hx + 3, hy + hr + 3), (hx - 1, hy + hr + 4), (bx - 4, by + 3), (bx + 2, by + 6)):
        fx, fy = int(fx), int(fy)
        if 0 <= fy < CANVAS_H and 0 <= fx < CANVAS_W and rows[fy][fx] in ("B", "D"):
            rows[fy][fx] = "M"
    return tuple(tuple(r) for r in rows)


def head_geometry(cx: float, cy: float, rx: float, ry: float) -> tuple[float, float, float]:
    """Head circle (centre x, centre y, radius) for a body centred at (cx, cy)."""
    return cx - rx * 0.42, cy - ry * 0.5, ry * 0.6


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
    hx, hy, hr = head_geometry(CX, cy, rx, ry)

    # far wing (behind the body), peeks out on the left/front side
    if pose.far_wing is not None:
        _draw_wing(g, (CX - rx * 0.1, cy + 1), -pose.far_wing, pose.wing_len * 0.85, 4.0, far=True)

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
    body = _body_layer(CX, cy, rx, ry, pose.upside_down)
    for y, row in enumerate(body):
        for x, c in enumerate(row):
            if c is None:
                continue
            if c == "O" and g[y][x] is not None:
                continue  # keep far wing / feet visible through the rim
            g[y][x] = c

    # beak: wedge pointing left from the face
    by = int(hy) + 2
    bx = int(hx - hr) + 2  # where the beak meets the face
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
    ex = int(hx) - 1
    ey = int(hy) - 3
    stamp(g, EYES.get(pose.eyes, EYES["open"]), ex - 2, ey - 1)
    stamp(g, ["..rR", ".rrR", "rr.."], ex + 4, ey + 4)
    if pose.sunglasses:
        # shades over the eye, strap running back around the head
        stamp(g, SUNGLASSES, ex - 3, ey - 1)
    elif pose.eyes == "pain":
        stamp(g, PAIN_BROW, ex - 3, ey - 4)

    # near wing (on top)
    _draw_wing(g, (CX + rx * 0.36, cy - 1), pose.wing, pose.wing_len, 5.5)

    # peck: swing the head forward and down toward the ground
    if pose.peck:
        neck = int(hy + hr * 0.7)
        dy, dx = 6, -3
        moved = {}
        for y in range(0, neck + 1):
            for x in range(0, CX + 2):
                c = g[y][x]
                if c is not None and (y < hy or x < CX - 4):
                    moved[(x, y)] = c
                    g[y][x] = None
        for (x, y), c in moved.items():
            nx_, ny_ = x + dx, y + dy
            if 0 <= nx_ < CANVAS_W and 0 <= ny_ < CANVAS_H:
                g[ny_][nx_] = c

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
    if pose.flash:
        g = [[FLASH.get(c, c) if c is not None else None for c in row] for row in g]
    if pose.mirror:
        g = [row[::-1] for row in g]
    return g


def head_center(pose: Pose) -> tuple[float, float]:
    cy = GROUND_Y - 3 - pose.hop - BODY_RY
    x, y, r = head_geometry(CX, cy, BODY_RX, BODY_RY)
    if pose.mirror:
        x = CANVAS_W - 1 - x
    return x, y - r * 0.3


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
    if pose.disco is not None:
        _draw_disco(g, pose.disco)
    for (x, y, small) in pose.hearts:
        art = HEART_SMALL if small else HEART
        stamp(g, art, int(round(x)) - len(art[0]) // 2, int(round(y)))
    def fx(x: float, w: int) -> int:
        """facing-left x -> canvas x"""
        return int(round(CANVAS_W - x - w)) if pose.mirror else int(round(x))

    for (x, y) in pose.seeds:
        stamp(g, SEED, fx(x, 3), int(round(y)) - 1, mirror=pose.mirror)
    for (x, y, big) in pose.tears:
        art = TEAR_BIG if big else TEAR
        stamp(g, art, fx(x, len(art[0])), int(round(y)))
    for (x, y, frame) in pose.feathers:
        stamp(g, FEATHER[frame % 2], int(round(x)), int(round(y)))
    for (x, y, small) in pose.zs:
        art = ZZZ_SMALL if small else ZZZ
        stamp(g, art, int(round(x)), int(round(y)))
    return g


DISCO_LIGHTS = "1234"


def _draw_disco(g: Grid, t: float) -> None:
    """Mirror ball hanging at the top with spinning facets, plus light spots sweeping the room."""
    cx, cy, r = 32, 8, 6
    for y in range(0, cy - r):
        g[y][cx] = "F"  # string
    spin = int(t * 8)
    for y in range(cy - r, cy + r + 1):
        for x in range(cx - r, cx + r + 1):
            dx, dy = x - cx + 0.5, y - cy + 0.5
            if dx * dx + dy * dy > r * r:
                continue
            facet = ((x + spin) // 2 + y // 2) % 5
            lit = (x - cx) < 0 and (y - cy) < 0  # top-left highlight
            if facet == 0:
                c = DISCO_LIGHTS[(x // 2 + y + spin) % 4]
            elif facet in (1, 2):
                c = "1" if lit else "5"
            else:
                c = "5" if lit else "6"
            g[y][x] = c
    # light spots: little sparkles orbiting the ball and sweeping across the floor and walls
    for k in range(8):
        a = t * 1.7 + k * math.pi / 4
        sx = int(round(cx + math.cos(a) * (14 + (k % 3) * 6)))
        sy = int(round(cy + 16 + math.sin(a) * (10 + (k % 2) * 8)))
        col = DISCO_LIGHTS[(k + int(t * 4)) % 4]
        if int(t * 6 + k) % 3 == 0:
            art = [f".{col}.", f"{col}{col}{col}", f".{col}."]
        else:
            art = [col]
        for j, row in enumerate(art):
            for i, ch in enumerate(row):
                px, py = sx + i - len(row) // 2, sy + j - len(art) // 2
                # only light up empty space so the raven stays readable
                if ch != "." and 0 <= px < CANVAS_W and 0 <= py < CANVAS_H and g[py][px] is None:
                    g[py][px] = ch


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
