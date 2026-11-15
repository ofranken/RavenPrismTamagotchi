"""
Pet simulation for the Raven Prism tamagotchi.

Pure Python (no Qt) so it can be unit tested and reasoned about on its own.

Stats (all 0..100):
    health  - overall wellbeing. Drives the visual mood:
              > 50 happy, <= 50 dizzy (stars), <= 25 groggy (dragging wings), 0 dead.
    food    - fed by productive apps (email, Outlook, Canvas...).
    energy  - "tired" stat. Restored when the phone is not being used (screen off);
              30+ minutes of screen-off counts as sleep and restores it much faster.
    play    - fed by walking (phone step counter), Zoom calls and looking at the raven.

Penalties: doomscrolling apps (Instagram, TikTok, X, Facebook) drain health and energy.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class Activity(Enum):
    DOOM = "doom"  # penalty apps
    FEED = "feed"  # productive apps that feed the raven
    PET = "pet"  # productive apps that pet / play with the raven
    NEUTRAL = "neutral"  # some other app is open
    RESTING = "resting"  # phone screen off (not using the phone)
    UNKNOWN = "unknown"  # no phone connected / stale


class Mood(Enum):
    HAPPY = "happy"
    SLEEPY = "sleepy"  # healthy but out of energy, or the user is asleep
    DIZZY = "dizzy"  # <= 50 health: stars spinning around the head
    GROGGY = "groggy"  # <= 25 health: walking groggily, dragging wings
    DEAD = "dead"  # 0 health: X eyes


# Android package name -> category. Edit categories.json to customise without code changes.
DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "doom": [
        "com.instagram.android",
        "com.instagram.lite",
        "com.zhiliaoapp.musically",  # TikTok
        "com.ss.android.ugc.trill",  # TikTok (some regions)
        "com.zhiliaoapp.musically.go",
        "com.twitter.android",  # X
        "com.facebook.katana",
        "com.facebook.lite",
    ],
    "feed": [
        "com.google.android.gm",  # Gmail
        "com.microsoft.office.outlook",
        "com.instructure.candroid",  # Canvas Student
        "com.instructure.teacher",  # Canvas Teacher
        "com.instructure.parentapp",
        "com.android.email",
        "com.samsung.android.email.provider",
        "com.yahoo.mobile.client.android.mail",
    ],
    "pet": [
        "us.zoom.videomeetings",  # Zoom
    ],
}

# Rates are "points per minute" of real time (multiplied by the speed factor).
PASSIVE_FOOD_DECAY = 0.5
PASSIVE_PLAY_DECAY = 0.4
PASSIVE_ENERGY_DECAY = 0.25  # while the phone is in use / unknown

DOOM_HEALTH = -4.0
DOOM_ENERGY = -1.5
DOOM_PLAY = -0.5

FEED_FOOD = +6.0
FEED_HEALTH = +1.5
PET_PLAY = +6.0
PET_HEALTH = +1.5

REST_ENERGY = +1.5  # screen off, short break
SLEEP_ENERGY = +4.0  # screen off for SLEEP_AFTER_S or longer
SLEEP_HEALTH = +0.5
SLEEP_AFTER_S = 30 * 60

STEPS_PER_PLAY_POINT = 50  # 1000 steps = +20 play
STEPS_PER_HEALTH_POINT = 200

NEGLECT_HEALTH = -1.0  # per empty stat (food / energy / play at 0)
WELLFED_HEALTH = +0.3  # slow regen while food, energy and play are all above 60

GAZE_PLAY = 6.0
GAZE_HEALTH = 1.0
GAZE_COOLDOWN_S = 20.0

REVIVE_PRODUCTIVE_S = 5 * 60  # 5 minutes of productive apps (or 500 steps) revives it
REVIVE_STEPS = 500

STALE_PHONE_S = 30.0
MAX_OFFLINE_CATCHUP_S = 12 * 3600


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def load_categories(path: Optional[Path] = None) -> dict[str, Activity]:
    cats = {k: list(v) for k, v in DEFAULT_CATEGORIES.items()}
    if path is not None and path.exists():
        try:
            data = json.loads(path.read_text())
            for key in ("doom", "feed", "pet"):
                if isinstance(data.get(key), list):
                    cats[key] = [str(p) for p in data[key]]
        except (OSError, ValueError):
            pass
    table: dict[str, Activity] = {}
    for key, activity in (("doom", Activity.DOOM), ("feed", Activity.FEED), ("pet", Activity.PET)):
        for pkg in cats[key]:
            table[pkg] = activity
    return table


@dataclass
class PhoneReport:
    """Latest heartbeat received from the companion phone app."""

    package: str = ""
    label: str = ""
    screen_on: bool = True
    steps_total: Optional[int] = None  # cumulative step counter since phone boot
    received_at: float = 0.0  # wall time (time.time())
    brightness: Optional[float] = None  # phone screen brightness 0..1 (1.0 = full = probably outdoors)
    lux: Optional[float] = None  # phone ambient light sensor


@dataclass
class PetState:
    health: float = 100.0
    food: float = 80.0
    energy: float = 80.0
    play: float = 80.0
    alive: bool = True
    revive_progress: float = 0.0  # seconds of productive time while dead
    revive_steps: int = 0
    last_steps_total: Optional[int] = None
    screen_off_since: Optional[float] = None  # wall time
    last_gaze_reward: float = 0.0
    saved_at: float = field(default_factory=time.time)
    steps_today: int = 0
    steps_day: str = ""

    # ---------------------------------------------------------------- derived
    @property
    def mood(self) -> Mood:
        if not self.alive or self.health <= 0:
            return Mood.DEAD
        if self.health <= 25:
            return Mood.GROGGY
        if self.health <= 50:
            return Mood.DIZZY
        if self.energy < 20:
            return Mood.SLEEPY
        return Mood.HAPPY

    def is_sleeping(self, now: float) -> bool:
        return self.screen_off_since is not None and now - self.screen_off_since >= SLEEP_AFTER_S

    # ---------------------------------------------------------------- inputs
    def apply_steps(self, steps_total: Optional[int], now: float) -> int:
        """Convert the phone's cumulative step counter into a delta. Returns new steps."""
        if steps_total is None or steps_total < 0:
            return 0
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        if day != self.steps_day:
            self.steps_day = day
            self.steps_today = 0
        if self.last_steps_total is None or steps_total < self.last_steps_total:
            # First report, or the phone rebooted and the counter reset.
            self.last_steps_total = steps_total
            return 0
        delta = steps_total - self.last_steps_total
        self.last_steps_total = steps_total
        # Ignore absurd jumps (e.g. counter glitch); 2000 steps between heartbeats is not real.
        delta = min(delta, 2000)
        if delta <= 0:
            return 0
        self.steps_today += delta
        if self.alive:
            self.play = clamp(self.play + delta / STEPS_PER_PLAY_POINT)
            self.health = clamp(self.health + delta / STEPS_PER_HEALTH_POINT)
        else:
            self.revive_steps += delta
            self._maybe_revive()
        return delta

    def update_screen(self, screen_on: bool, now: float) -> None:
        if screen_on:
            self.screen_off_since = None
        elif self.screen_off_since is None:
            self.screen_off_since = now

    def on_gazed(self, now: float) -> bool:
        """User looked at the raven. Returns True if a reward was granted."""
        if not self.alive or now - self.last_gaze_reward < GAZE_COOLDOWN_S:
            return False
        self.last_gaze_reward = now
        self.play = clamp(self.play + GAZE_PLAY)
        self.health = clamp(self.health + GAZE_HEALTH)
        return True

    # ---------------------------------------------------------------- simulation
    def tick(self, dt_s: float, activity: Activity, now: float) -> None:
        """Advance the simulation by dt_s seconds (already speed-scaled)."""
        if dt_s <= 0:
            return
        m = dt_s / 60.0

        if not self.alive:
            if activity in (Activity.FEED, Activity.PET):
                self.revive_progress += dt_s
                self._maybe_revive()
            return

        sleeping = activity == Activity.RESTING and self.is_sleeping(now)

        # passive decay (slower while asleep)
        decay = 0.4 if sleeping else 1.0
        self.food = clamp(self.food - PASSIVE_FOOD_DECAY * m * decay)
        self.play = clamp(self.play - PASSIVE_PLAY_DECAY * m * decay)
        if activity != Activity.RESTING:
            self.energy = clamp(self.energy - PASSIVE_ENERGY_DECAY * m)

        if activity == Activity.DOOM:
            self.health = clamp(self.health + DOOM_HEALTH * m)
            self.energy = clamp(self.energy + DOOM_ENERGY * m)
            self.play = clamp(self.play + DOOM_PLAY * m)
        elif activity == Activity.FEED:
            self.food = clamp(self.food + FEED_FOOD * m)
            self.health = clamp(self.health + FEED_HEALTH * m)
        elif activity == Activity.PET:
            self.play = clamp(self.play + PET_PLAY * m)
            self.health = clamp(self.health + PET_HEALTH * m)
        elif activity == Activity.RESTING:
            if sleeping:
                self.energy = clamp(self.energy + SLEEP_ENERGY * m)
                self.health = clamp(self.health + SLEEP_HEALTH * m)
            else:
                self.energy = clamp(self.energy + REST_ENERGY * m)

        empty = sum(1 for v in (self.food, self.energy, self.play) if v <= 0)
        if empty:
            self.health = clamp(self.health + NEGLECT_HEALTH * empty * m)
        elif activity != Activity.DOOM and min(self.food, self.energy, self.play) > 60:
            self.health = clamp(self.health + WELLFED_HEALTH * m)

        if self.health <= 0:
            self._die()

    def _die(self) -> None:
        self.health = 0.0
        self.alive = False
        self.revive_progress = 0.0
        self.revive_steps = 0

    def _maybe_revive(self) -> None:
        if self.alive:
            return
        if self.revive_progress >= REVIVE_PRODUCTIVE_S or self.revive_steps >= REVIVE_STEPS:
            self.alive = True
            self.health = 35.0
            self.food = max(self.food, 40.0)
            self.energy = max(self.energy, 50.0)
            self.play = max(self.play, 40.0)
            self.revive_progress = 0.0
            self.revive_steps = 0

    @property
    def revive_fraction(self) -> float:
        return max(
            self.revive_progress / REVIVE_PRODUCTIVE_S, self.revive_steps / REVIVE_STEPS
        )

    # ---------------------------------------------------------------- persistence
    def to_json(self) -> str:
        d = asdict(self)
        d["saved_at"] = time.time()
        return json.dumps(d)

    @classmethod
    def from_json(cls, text: str) -> "PetState":
        data = json.loads(text)
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(self.to_json())
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path, now: Optional[float] = None) -> "PetState":
        """Load saved state and catch up on time spent while the app was closed."""
        now = time.time() if now is None else now
        try:
            state = cls.from_json(path.read_text())
        except (OSError, ValueError, TypeError):
            return cls()
        away = clamp(now - state.saved_at, 0, MAX_OFFLINE_CATCHUP_S)
        if away > 0:
            # We don't know what the phone did while we were closed; assume plain neutral use.
            state.tick(away, Activity.NEUTRAL, now)
        return state


def classify(report: Optional[PhoneReport], table: dict[str, Activity], now: float) -> Activity:
    if report is None:
        return Activity.UNKNOWN
    # A sleeping phone may stop sending heartbeats (Doze), so "screen off" stays valid
    # until the phone tells us otherwise. The phone reports screen-on immediately on wake.
    if not report.screen_on:
        return Activity.RESTING
    if now - report.received_at > STALE_PHONE_S:
        return Activity.UNKNOWN
    return table.get(report.package, Activity.NEUTRAL)
