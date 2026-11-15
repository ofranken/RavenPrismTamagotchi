"""Render GIFs of every procedural animation, straight from the real animator + pixel art code.

    python raven_pet/tools/make_gifs.py            # writes docs/gifs/*.gif

Nothing here is hand-animated: each GIF runs RavenAnimator.update() at the app's 12 fps
and composes the frames exactly as the glasses app does.
"""

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "raven_pet"))

from PIL import Image  # noqa: E402

from animator import RavenAnimator  # noqa: E402
from pet_state import Mood  # noqa: E402
from pixel_art import CANVAS_H, CANVAS_W, compose, frame_to_rgba  # noqa: E402

OUT = ROOT / "docs" / "gifs"
FPS = 12
SCALE = 4
STAGE_W = 128  # logical px: the raven can wander across this
BG = (13, 13, 20, 255)


def render(name: str, seconds: float, mood: Mood, setup=None, **flags) -> Path:
    anim = RavenAnimator(area_width=STAGE_W - CANVAS_W, scale=1, rng=random.Random(7))
    if setup:
        setup(anim)
    frames = []
    for _ in range(int(seconds * FPS)):
        pose = anim.update(1 / FPS, mood, **flags)
        sprite = Image.frombytes("RGBA", (CANVAS_W, CANVAS_H), frame_to_rgba(compose(pose)))
        stage = Image.new("RGBA", (STAGE_W, CANVAS_H), BG)
        stage.alpha_composite(sprite, (int(round(anim.render_x)), 0))
        frames.append(stage.resize((STAGE_W * SCALE, CANVAS_H * SCALE), Image.NEAREST).convert("RGB"))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=int(1000 / FPS), loop=0, optimize=True)
    return path


def main() -> None:
    jobs = [
        ("happy", 8, Mood.HAPPY, None, {}),
        ("love_hearts", 4, Mood.HAPPY, lambda a: a.start_love(), {}),
        ("eating_seeds", 5, Mood.HAPPY, None, {"feeding": True}),
        ("hurt_doomscrolling", 5, Mood.HAPPY, None, {"hurting": True}),
        ("sleeping", 5, Mood.SLEEPY, None, {}),
        ("dizzy_half_health", 5, Mood.DIZZY, None, {}),
        ("groggy_quarter_health", 8, Mood.GROGGY, None, {}),
        ("dead", 2, Mood.DEAD, None, {}),
        ("sunglasses", 6, Mood.HAPPY, None, {"sunglasses": True}),
        ("disco_maxed_stats", 6, Mood.HAPPY, None, {"disco": True}),
    ]
    for name, secs, mood, setup, flags in jobs:
        print(render(name, secs, mood, setup, **flags).relative_to(ROOT))


if __name__ == "__main__":
    main()
