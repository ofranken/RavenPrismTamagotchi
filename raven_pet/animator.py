"""
Behaviour / animation state machine for the raven. Pure Python (no Qt).

`RavenAnimator.update(dt, mood, ...)` moves the raven around the play area and
returns a `Pose` for `pixel_art.compose`, plus the raven's x position in app pixels.

Behaviours by mood:
    HAPPY   hops around between random spots, flaps its wings, blinks
    LOVE    (user is looking at it) happy eyes, bouncy hops, flapping, hearts
    SLEEPY  sits squashed with eyes closed and Z's floating up
    DIZZY   (<= 50 health) sways in place, spiral eyes, stars orbit its head
    GROGGY  (<= 25 health) walks slowly, dragging its wings, stars orbit its head
    DEAD    on its back, feet up, X eyes
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from pet_state import Mood
from pixel_art import CANVAS_W, Pose

LOVE_DURATION = 2.6
HOP_DURATION = 0.42
HOP_HEIGHT = 7


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    small: bool


@dataclass
class RavenAnimator:
    area_width: float  # px the raven's widget may move across
    scale: int = 5
    x: float = 0.0
    facing_right: bool = False
    t: float = 0.0
    rng: random.Random = field(default_factory=random.Random)

    # internal
    _target_x: float | None = None
    _hop_t: float = -1.0  # progress of current hop (s), -1 = not hopping
    _hop_from: float = 0.0
    _hop_to: float = 0.0
    _idle_until: float = 0.0
    _flap_until: float = 0.0
    _blink_at: float = 2.0
    _love_until: float = 0.0
    _heart_timer: float = 0.0
    _z_timer: float = 0.0
    _hearts: list[Particle] = field(default_factory=list)
    _zs: list[Particle] = field(default_factory=list)
    _walk_dir: int = -1

    def __post_init__(self) -> None:
        self.x = self.area_width * 0.5

    # ------------------------------------------------------------------ events
    def start_love(self) -> None:
        self._love_until = self.t + LOVE_DURATION
        self._heart_timer = 0.0
        self._zs.clear()  # wake up for the cuddle

    @property
    def in_love(self) -> bool:
        return self.t < self._love_until

    # ------------------------------------------------------------------ update
    def update(self, dt: float, mood: Mood) -> Pose:
        self.t += dt
        pose = Pose(mirror=self.facing_right)

        if mood == Mood.DEAD:
            self._hearts.clear()
            pose.eyes = "dead"
            pose.upside_down = True
            pose.wing = 100
            pose.far_wing = 100
            pose.mirror = False
            self._update_particles(dt)
            pose.zs = []
            return pose

        if self.in_love:
            self._love(dt, pose)
        elif mood == Mood.HAPPY:
            self._happy(dt, pose)
        elif mood == Mood.SLEEPY:
            self._sleepy(dt, pose)
        elif mood == Mood.DIZZY:
            self._dizzy(dt, pose)
        elif mood == Mood.GROGGY:
            self._groggy(dt, pose)

        if mood in (Mood.DIZZY, Mood.GROGGY):
            pose.stars = self.t * (3.2 if mood == Mood.DIZZY else 2.2)

        # particles
        if self.in_love:
            self._heart_timer -= dt
            if self._heart_timer <= 0:
                self._heart_timer = 0.22
                self._hearts.append(
                    Particle(
                        x=self.rng.uniform(16, CANVAS_W - 16),
                        y=self.rng.uniform(14, 24),
                        vx=self.rng.uniform(-3, 3),
                        vy=-self.rng.uniform(9, 14),
                        life=self.rng.uniform(1.0, 1.5),
                        small=self.rng.random() < 0.4,
                    )
                )
        if mood == Mood.SLEEPY and not self.in_love:
            self._z_timer -= dt
            if self._z_timer <= 0:
                self._z_timer = 1.1
                zx = 44 if not self.facing_right else 14
                self._zs.append(Particle(zx, 22, 3 if not self.facing_right else -3, -5, 2.6, self.rng.random() < 0.5))
        self._update_particles(dt)
        pose.hearts = [(p.x, p.y, p.small) for p in self._hearts if p.life > 0.25 or int(p.life * 20) % 2]
        pose.zs = [(p.x, p.y, p.small) for p in self._zs]
        pose.mirror = self.facing_right
        return pose

    def _update_particles(self, dt: float) -> None:
        for plist in (self._hearts, self._zs):
            for p in plist:
                p.x += p.vx * dt
                p.y += p.vy * dt
                p.life -= dt
            plist[:] = [p for p in plist if p.life > 0 and p.y > -8]

    # ------------------------------------------------------------------ behaviours
    def _blink(self, pose: Pose) -> None:
        if self.t >= self._blink_at:
            pose.eyes = "blink"
            if self.t >= self._blink_at + 0.12:
                self._blink_at = self.t + self.rng.uniform(2.0, 5.0)

    def _hop_step(self, dt: float, pose: Pose) -> bool:
        """Advance the current hop. Returns True while hopping."""
        if self._hop_t < 0:
            return False
        self._hop_t += dt
        u = min(1.0, self._hop_t / HOP_DURATION)
        self.x = self._hop_from + (self._hop_to - self._hop_from) * u
        pose.hop = int(round(math.sin(u * math.pi) * HOP_HEIGHT))
        pose.squash = -1 if u < 0.5 else 0
        pose.wing = 70 + 60 * math.sin(self._hop_t * 30)
        pose.wing_len = 15
        pose.far_wing = pose.wing
        if u >= 1.0:
            self._hop_t = -1.0
            pose.squash = 1  # landing squash frame
            pose.hop = 0
        return True

    def _start_hop(self, to_x: float) -> None:
        to_x = max(0.0, min(self.area_width, to_x))
        self._hop_from = self.x
        self._hop_to = to_x
        self._hop_t = 0.0
        if abs(to_x - self.x) > 1:
            self.facing_right = to_x > self.x

    def _happy(self, dt: float, pose: Pose) -> None:
        self._blink(pose)
        if self._hop_step(dt, pose):
            return
        if self.t < self._flap_until:
            pose.wing = 90 + 70 * math.sin(self.t * 26)
            pose.wing_len = 16
            pose.far_wing = pose.wing
            pose.hop = 1 if math.sin(self.t * 26) > 0 else 0
            return
        if self._target_x is not None:
            if abs(self._target_x - self.x) < 2:
                self._target_x = None
                self._idle_until = self.t + self.rng.uniform(1.5, 4.0)
            else:
                step = self.scale * 9 * (1 if self._target_x > self.x else -1)
                nxt = self.x + step
                if (step > 0 and nxt > self._target_x) or (step < 0 and nxt < self._target_x):
                    nxt = self._target_x
                self._start_hop(nxt)
                return
        # idle: gentle breathing bob
        pose.squash = 1 if math.sin(self.t * 3) > 0.85 else 0
        if self.t >= self._idle_until:
            r = self.rng.random()
            if r < 0.3:
                self._flap_until = self.t + 0.9
            elif r < 0.45:
                self._start_hop(self.x)  # hop in place
            else:
                self._target_x = self.rng.uniform(0, self.area_width)
            self._idle_until = self.t + self.rng.uniform(1.0, 3.0)

    def _love(self, dt: float, pose: Pose) -> None:
        pose.eyes = "happy"
        pose.beak_open = int(self.t * 4) % 2 == 0
        if self._hop_step(dt, pose):
            pose.eyes = "happy"
            return
        self._target_x = None
        self._start_hop(self.x)  # bounce in place

    def _sleepy(self, dt: float, pose: Pose) -> None:
        self._target_x = None
        if self._hop_step(dt, pose):
            return
        pose.eyes = "closed"
        pose.feet = "tuck"
        pose.squash = 1
        pose.hop = -2  # settle down onto the ground
        pose.wing = 20

    def _dizzy(self, dt: float, pose: Pose) -> None:
        self._target_x = None
        if self._hop_step(dt, pose):
            return
        pose.eyes = "dizzy"
        sway = math.sin(self.t * 2.4)
        pose.lean = 1 if sway > 0.45 else (-1 if sway < -0.45 else 0)
        pose.wing = 12
        # the occasional stumble
        if self.t >= self._idle_until:
            self._idle_until = self.t + self.rng.uniform(2.0, 4.0)
            self.x = max(0.0, min(self.area_width, self.x + self.rng.choice((-1, 1)) * self.scale * 2))
            pose.feet = "walk_a"

    def _groggy(self, dt: float, pose: Pose) -> None:
        self._target_x = None
        self._hop_t = -1.0
        pose.eyes = "groggy" if int(self.t * 0.7) % 4 else "blink"
        speed = self.scale * 3.0  # px/s, slow trudge
        self.x += self._walk_dir * speed * dt
        if self.x <= 0 or self.x >= self.area_width:
            self.x = max(0.0, min(self.area_width, self.x))
            self._walk_dir *= -1
        self.facing_right = self._walk_dir > 0
        step = int(self.t * 2.2) % 2
        pose.feet = "walk_a" if step else "walk_b"
        pose.lean = -1 if step else 0
        pose.hop = 0
        pose.squash = 1 if step else 0
        # wings drooped and dragging along the ground
        pose.wing = 33
        pose.wing_len = 21
        pose.far_wing = 28
