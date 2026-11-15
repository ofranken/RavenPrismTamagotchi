"""Render a contact sheet of raven poses to PNG (no Qt needed).

    python raven_pet/tools/render_preview.py out.png
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from pixel_art import CANVAS_H, CANVAS_W, Pose, compose, frame_to_rgba  # noqa: E402

POSES = {
    "happy": Pose(),
    "hop": Pose(hop=6, squash=-1, wing=70, far_wing=60),
    "flap up": Pose(wing=160, wing_len=17, far_wing=160, hop=2),
    "land": Pose(squash=1, eyes="happy"),
    "love": Pose(eyes="happy", hearts=[(20, 6, False), (44, 2, True), (36, 12, False)], beak_open=True),
    "sleepy": Pose(eyes="closed", squash=1, feet="tuck", zs=[(46, 14, False), (52, 6, True)]),
    "dizzy": Pose(eyes="dizzy", stars=0.6, lean=1, wing=15),
    "groggy": Pose(eyes="groggy", stars=2.0, lean=-1, wing=35, wing_len=21, far_wing=30, feet="walk_a"),
    "groggy R": Pose(eyes="groggy", stars=3.0, wing=35, wing_len=21, far_wing=30, feet="walk_b", mirror=True),
    "dead": Pose(eyes="dead", upside_down=True, wing=100, far_wing=100),
    "eat": Pose(seeds=[(5, 59), (10, 59), (15, 59), (8, 50)], peck=True, eyes="happy", feet="walk_a"),
    "eat up": Pose(seeds=[(5, 59), (10, 59), (15, 59)]),
    "pain": Pose(eyes="pain", beak_open=True, squash=1, wing=8, wing_len=14, tears=[(19, 30, False), (17, 38, True)], feathers=[(44, 34, 0), (52, 46, 1)]),
    "pain flash": Pose(eyes="pain", flash=True, squash=1, wing=8, wing_len=14, tears=[(19, 32, False)]),
    "disco": Pose(disco=1.3, eyes="happy", hop=3, wing=150, wing_len=16, far_wing=150, sunglasses=True),
    "sunglasses": Pose(sunglasses=True, wing=60, far_wing=50, hop=2),
}


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "preview.png")
    scale = 5
    cols = 5
    rows = (len(POSES) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * CANVAS_W * scale, rows * CANVAS_H * scale), (0, 0, 0, 255))
    for k, pose in enumerate(POSES.values()):
        img = Image.frombytes("RGBA", (CANVAS_W, CANVAS_H), frame_to_rgba(compose(pose)))
        img = img.resize((CANVAS_W * scale, CANVAS_H * scale), Image.NEAREST)
        sheet.alpha_composite(img, ((k % cols) * CANVAS_W * scale, (k // cols) * CANVAS_H * scale))
    sheet.save(out)
    print(out)


if __name__ == "__main__":
    main()
