"""
Raven Pet - a pixel-art tamagotchi raven for Raven Prism.

The raven lives on the glasses and reacts to how you use your phone (via the
companion Android app in ../android):
    * Instagram / TikTok / X / Facebook hurt it (dizzy at 50% health, groggy at 25%, dead at 0)
    * Email / Outlook / Canvas feed it, Zoom pets it
    * Walking (phone step counter) plays with it
    * Not using your phone lets it rest; 30+ minutes screen-off counts as sleep
    * Looking at it makes it happy (hearts!)

Run in the simulator:   python main.py
Deploy to the glasses:  python main.py deploy

Simulator keys: 1 doomscroll  2 email  3 zoom  4 other app  5 screen off  6 asleep
                0 clear phone  W +250 steps  L love  F toggle 60x speed  D -25 health  R reset
                T toggle sunglasses  M max all stats (disco)
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QCursor, QImage, QKeyEvent, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from raven_framework.components.text_box import TextBox
from raven_framework.core.raven_app import RavenApp
from raven_framework.core.run_app import RunApp
from raven_framework.helpers.animation_utils import fade_in
from raven_framework.helpers.routine import Routine

from animator import RavenAnimator
from pet_state import (
    SLEEP_AFTER_S,
    Activity,
    Mood,
    PetState,
    PhoneReport,
    classify,
    load_categories,
)
from phone_link import HTTP_PORT, PhoneLink, local_ip
from pixel_art import CANVAS_H, CANVAS_W, CX, GROUND_Y, ICONS, PALETTE, Grid, compose, frame_to_rgba

APP_ID = ""  # fill in for deployment
APP_KEY = ""

HERE = Path(__file__).resolve().parent
STATE_PATH = Path(os.environ.get("RAVEN_PET_STATE", Path.home() / ".local/share/raven_pet/state.json"))
CATEGORIES_PATH = HERE / "categories.json"

FPS = 12
PIXEL = 5  # screen px per art pixel
SAVE_EVERY_S = 30.0
GAZE_DWELL_S = 0.6  # how long you have to look at the raven before it reacts
LOVE_COOLDOWN_S = 6.0
TOAST_S = 4.0
SUNNY_BRIGHTNESS = 0.95  # phone screen at (near) full brightness => probably outside in the sun
DISCO_AT = 95  # every stat at least this high => disco party
SUNNY_LUX = 10_000  # phone light sensor: direct sunlight is 10k-100k lux, a bright room ~500
SUNGLASSES_HOLD_S = 10 * 60  # keep the shades on a while: the phone goes back in a pocket


def lenses_tinted() -> bool:
    """True when the glasses' lenses are tinted.

    The simulator models tint (its "Tint" button flips raven_simulator.ENABLE_TINT), so we
    read that. The Raven SDK has no device API for lens tint yet; on the glasses this
    returns False and the sunglasses rely on the phone's screen brightness instead.
    """
    sim = sys.modules.get("raven_framework.core.raven_simulator")
    return bool(getattr(sim, "ENABLE_TINT", False)) if sim is not None else False


def grid_to_qimage(grid: Grid) -> QImage:
    data = frame_to_rgba(grid)
    h, w = len(grid), len(grid[0])
    return QImage(data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()


class PixelCanvas(QWidget):
    """Draws a pixel grid scaled up with hard (nearest-neighbour) edges."""

    def __init__(self, cols: int, rows: int, scale: int, parent=None) -> None:
        super().__init__(parent)
        self._scale = scale
        self.setFixedSize(cols * scale, rows * scale)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._img: QImage | None = None

    def set_grid(self, grid: Grid) -> None:
        self._img = grid_to_qimage(grid)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self._img is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawImage(QRect(0, 0, self.width(), self.height()), self._img)
        p.end()


class StatsHud(QWidget):
    """Four pixel-art stat rows: icon + 10 segment bar. Icons carry the meaning, not colour."""

    ROWS = ("health", "food", "energy", "play")
    BAR_COLORS = {
        "health": QColor(255, 72, 110),
        "food": QColor(246, 112, 88),
        "energy": QColor(255, 214, 64),
        "play": QColor(170, 210, 255),
    }
    PX = 3
    SEG_W = 12
    SEG_H = 15
    SEGMENTS = 10
    ROW_H = 30

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        width = 8 * self.PX + 12 + self.SEGMENTS * (self.SEG_W + 3)
        self.setFixedSize(width, self.ROW_H * len(self.ROWS))
        self._values = {k: 100.0 for k in self.ROWS}
        self._icons = {k: self._icon_image(k) for k in self.ROWS}
        self._blink = False

    @staticmethod
    def _icon_image(name: str) -> QImage:
        art = ICONS[name]
        grid: Grid = [[None if ch == "." else ch for ch in row] for row in art]
        return grid_to_qimage(grid)

    def set_values(self, values: dict[str, float], blink: bool) -> None:
        self._values = values
        self._blink = blink
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        dim = QColor(70, 74, 110)
        for i, key in enumerate(self.ROWS):
            y = i * self.ROW_H
            p.drawImage(QRect(0, y + 3, 8 * self.PX, 8 * self.PX), self._icons[key])
            filled = int(round(self._values.get(key, 0) / 10.0))
            low = filled <= 2
            for s in range(self.SEGMENTS):
                x = 8 * self.PX + 12 + s * (self.SEG_W + 3)
                on = s < filled and not (low and self._blink)
                p.fillRect(x, y + 7, self.SEG_W, self.SEG_H, self.BAR_COLORS[key] if on else dim)
        p.end()


class RavenPetApp(RavenApp):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.state = PetState.load(STATE_PATH)
        self.categories = load_categories(CATEGORIES_PATH)
        self.speed = float(os.environ.get("RAVEN_PET_SPEED", "1"))
        self.report: PhoneReport | None = None
        self.activity = Activity.UNKNOWN
        self._last_wall = time.time()
        self._last_save = self._last_wall
        self._gaze_since: float | None = None
        # Last gaze point (global coords) taken from mouse events delivered to this app.
        # The simulator draws a scaled composite and forwards remapped mouse events to the
        # hidden real widget, so QCursor.pos() does not line up with the raven there.
        self._gaze_global: QPoint | None = None
        self._gaze_events_seen = False
        self._last_love = 0.0
        self._toast = ""
        self._toast_until = 0.0
        self._status_text = ""
        self._sunny_until = 0.0
        self._force_sunglasses = False
        self._frame = 0

        app_w, app_h = self.app.width(), self.app.height()

        self.hud = StatsHud()
        self.status = TextBox("", font_size=18, text_color="#C8CCFF", width=app_w - 140)
        self.raven = PixelCanvas(CANVAS_W, CANVAS_H, PIXEL)
        self.raven_y = app_h - self.raven.height() - 10
        self.anim = RavenAnimator(area_width=app_w - self.raven.width(), scale=PIXEL)

        self.app.add(self.hud, 24, 24)
        self.app.add(self.status, 24, 24 + self.hud.height() + 8)
        self.app.add(self.raven, int(self.anim.x), self.raven_y)
        for w in (self, self.app, self.hud, self.status, self.raven):
            w.setMouseTracking(True)
        QApplication.instance().installEventFilter(self)

        self.port = int(os.environ.get("RAVEN_PET_PORT", HTTP_PORT))
        self.link = PhoneLink(
            port=self.port,
            pair_code=os.environ.get("RAVEN_PET_PAIR", ""),
            classifier=lambda r: classify(r, self.categories, time.time()).value,
        )
        self.link.publish_status(self._status_payload())
        self._link_ok = self.link.start()
        self._ip = local_ip()

        self._render(0.0)
        self.loop = Routine(interval_ms=int(1000 / FPS), invoke=self._on_frame, mode="repeat")
        fade_in(self.app)

    # ------------------------------------------------------------------ main loop
    def _on_frame(self) -> None:
        now = time.time()
        dt = min(0.5, max(0.0, now - self._last_wall))
        self._last_wall = now

        for report in self.link.drain():
            self._handle_report(report, now)

        self.activity = classify(self.report, self.categories, now)
        self.state.tick(dt * self.speed, self.activity, now)

        self._check_gaze(dt, now)
        self._render(dt)

        self._frame += 1
        if self._frame % FPS == 0:
            self.link.publish_status(self._status_payload())
            self._update_texts(now)
        if now - self._last_save > SAVE_EVERY_S:
            self._save()

    def _handle_report(self, report: PhoneReport, now: float) -> None:
        self.report = report
        self.state.update_screen(report.screen_on, now)
        bright_screen = report.brightness is not None and report.brightness >= SUNNY_BRIGHTNESS
        sunlight = report.lux is not None and report.lux >= SUNNY_LUX
        if report.screen_on:
            if bright_screen or sunlight:
                if now >= self._sunny_until:
                    self._show_toast("Sunny out! Raven put on its shades", now)
                self._sunny_until = now + SUNGLASSES_HOLD_S
            else:
                # phone is on and it isn't sunny any more: shades off right away.
                # (while the screen is off - phone in a pocket - the shades stay on until the hold runs out)
                self._sunny_until = 0.0
        steps = self.state.apply_steps(report.steps_total, now)
        if steps >= 20:
            self._show_toast(f"+{steps} steps - Raven played!", now)

    def _display_mood(self) -> Mood:
        mood = self.state.mood
        if mood == Mood.HAPPY and self.activity == Activity.RESTING and self.state.is_sleeping(time.time()):
            mood = Mood.SLEEPY  # raven sleeps when you do
        return mood

    def _wearing_sunglasses(self) -> bool:
        return self._force_sunglasses or lenses_tinted() or time.time() < self._sunny_until

    def _render(self, dt: float) -> None:
        s = self.state
        disco = s.alive and min(s.health, s.food, s.energy, s.play) >= DISCO_AT
        pose = self.anim.update(
            dt,
            self._display_mood(),
            disco=disco,
            feeding=self.activity == Activity.FEED,
            hurting=self.activity == Activity.DOOM,
            sunglasses=self._wearing_sunglasses(),
        )
        self.raven.set_grid(compose(pose))
        self.raven.move(int(self.anim.render_x), self.raven_y)
        values = {
            "health": self.state.health,
            "food": self.state.food,
            "energy": self.state.energy,
            "play": self.state.play,
        }
        self.hud.set_values(values, blink=(self._frame // 6) % 2 == 0)

    # ------------------------------------------------------------------ gaze
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        """Track gaze from mouse events aimed at this app (works with the simulator's remapping)."""
        etype = event.type()
        if etype == QEvent.Type.MouseMove and isinstance(obj, QWidget) and (obj is self or self.isAncestorOf(obj)):
            self._gaze_events_seen = True
            self._gaze_global = event.globalPosition().toPoint()
        elif etype == QEvent.Type.Leave and obj is self:
            self._gaze_global = None
        return False

    def _looking_at_raven(self) -> bool:
        """True when the gaze (cursor in the simulator) is on the raven's body."""
        if self._gaze_events_seen:
            if self._gaze_global is None:
                return False
            pos: QPoint = self.raven.mapFromGlobal(self._gaze_global)
        else:
            pos = self.raven.mapFromGlobal(QCursor.pos())
        if not self.raven.rect().contains(pos):
            return False
        # generous ellipse around the body: eye tracking is only ~2-3 degrees accurate
        cx = (CX + 0.5) * PIXEL
        if self.anim.facing_right:
            cx = self.raven.width() - cx
        cy = (GROUND_Y - 3 - 16) * PIXEL
        rx, ry = 24 * PIXEL, 24 * PIXEL
        dx, dy = (pos.x() - cx) / rx, (pos.y() - cy) / ry
        return dx * dx + dy * dy <= 1.0

    def _check_gaze(self, dt: float, now: float) -> None:
        if self.state.mood == Mood.DEAD or not self._looking_at_raven():
            self._gaze_since = None
            return
        if self._gaze_since is None:
            self._gaze_since = now
        if now - self._gaze_since >= GAZE_DWELL_S and now - self._last_love >= LOVE_COOLDOWN_S:
            self._last_love = now
            self.anim.start_love()
            self.state.on_gazed(now)

    # ------------------------------------------------------------------ text
    def _show_toast(self, text: str, now: float) -> None:
        self._toast = text
        self._toast_until = now + TOAST_S
        self._update_texts(now)

    def _update_texts(self, now: float) -> None:
        if now < self._toast_until:
            text = self._toast
        elif self.state.mood == Mood.DEAD:
            text = f"Raven fainted. Be productive or walk to revive ({int(self.state.revive_fraction * 100)}%)"
        else:
            label = (self.report.label or self.report.package) if self.report else ""
            text = {
                Activity.DOOM: f"Ow! {label} is hurting Raven!",
                Activity.FEED: f"{label} - feeding Raven",
                Activity.PET: f"{label} - Raven feels loved",
                Activity.NEUTRAL: "",
                Activity.RESTING: "Sleeping... zzz" if self.state.is_sleeping(now) else "Phone down - Raven is resting",
                Activity.UNKNOWN: (
                    f"Phone not connected ({self._ip}:{self.port})" if self._link_ok else "Phone link offline"
                ),
            }[self.activity]
        if self.speed != 1:
            text = f"[{self.speed:g}x] {text}".rstrip()
        if text != self._status_text:
            self._status_text = text
            self.status.set_text(text)

    def _status_payload(self) -> dict:
        s = self.state
        return {
            "health": round(s.health, 1),
            "food": round(s.food, 1),
            "energy": round(s.energy, 1),
            "play": round(s.play, 1),
            "mood": self._display_mood().value,
            "alive": s.alive,
            "revive": round(s.revive_fraction, 2),
            "steps_today": s.steps_today,
            "activity": self.activity.value,
            "sunglasses": self._wearing_sunglasses(),
        }

    # ------------------------------------------------------------------ persistence / exit
    def _save(self) -> None:
        self._last_save = time.time()
        try:
            self.state.save(STATE_PATH)
        except OSError as e:
            print(f"[raven-pet] could not save state: {e}")

    def on_home_clicked(self) -> None:
        self._save()
        self.loop.stop()
        self.link.stop()
        QApplication.instance().removeEventFilter(self)
        super().on_home_clicked()

    # ------------------------------------------------------------------ simulator keys
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        now = time.time()
        k = event.key()
        sim = {
            Qt.Key.Key_1: ("com.instagram.android", "Instagram", True),
            Qt.Key.Key_2: ("com.google.android.gm", "Gmail", True),
            Qt.Key.Key_3: ("us.zoom.videomeetings", "Zoom", True),
            Qt.Key.Key_4: ("com.android.chrome", "Chrome", True),
            Qt.Key.Key_5: ("", "", False),
            Qt.Key.Key_6: ("", "", False),
        }
        if self.state.last_steps_total is None:
            self.state.last_steps_total = 0
        steps = self.state.last_steps_total  # simulated reports keep the step count unchanged
        if k in sim:
            pkg, label, screen_on = sim[k]
            if k == Qt.Key.Key_6:
                self.state.screen_off_since = now - SLEEP_AFTER_S - 1
            self._handle_report(PhoneReport(pkg, label, screen_on, steps, now), now)
        elif k == Qt.Key.Key_0:
            self.report = None
        elif k == Qt.Key.Key_W:
            base = self.report or PhoneReport(screen_on=True, received_at=now)
            self._handle_report(PhoneReport(base.package, base.label, base.screen_on, steps + 250, now), now)
        elif k == Qt.Key.Key_L:
            self._last_love = now
            self.anim.start_love()
            self.state.on_gazed(now)
        elif k == Qt.Key.Key_F:
            self.speed = 60.0 if self.speed == 1 else 1.0
        elif k == Qt.Key.Key_D:
            self.state.health = max(0.0, self.state.health - 25)
            if self.state.health <= 0:
                self.state._die()
        elif k == Qt.Key.Key_R:
            self.state = PetState()
        elif k == Qt.Key.Key_M:  # max out every stat (disco!)
            s = self.state
            s.health = s.food = s.energy = s.play = 100.0
        elif k == Qt.Key.Key_T:
            self._force_sunglasses = not self._force_sunglasses
        else:
            super().keyPressEvent(event)
            return
        self._update_texts(now)


if __name__ == "__main__":
    import faulthandler
    import signal

    # `kill -USR1 <pid>` prints every thread's stack: handy if the app ever freezes
    if hasattr(signal, "SIGUSR1"):
        faulthandler.register(signal.SIGUSR1, all_threads=True)
    sys.path.insert(0, str(HERE))
    RunApp.run(lambda: RavenPetApp(), app_id=APP_ID, app_key=APP_KEY)
