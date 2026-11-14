import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from animator import RavenAnimator  # noqa: E402
from pet_state import (  # noqa: E402
    SLEEP_AFTER_S,
    Activity,
    Mood,
    PetState,
    PhoneReport,
    classify,
    load_categories,
)
from pixel_art import CANVAS_H, CANVAS_W, compose  # noqa: E402

NOW = 1_800_000_000.0
TABLE = load_categories()


def test_classify_apps():
    def rep(pkg, screen=True, age=0.0):
        return PhoneReport(pkg, "", screen, None, NOW - age)

    assert classify(rep("com.instagram.android"), TABLE, NOW) == Activity.DOOM
    assert classify(rep("com.zhiliaoapp.musically"), TABLE, NOW) == Activity.DOOM
    assert classify(rep("com.twitter.android"), TABLE, NOW) == Activity.DOOM
    assert classify(rep("com.facebook.katana"), TABLE, NOW) == Activity.DOOM
    assert classify(rep("com.google.android.gm"), TABLE, NOW) == Activity.FEED
    assert classify(rep("com.microsoft.office.outlook"), TABLE, NOW) == Activity.FEED
    assert classify(rep("com.instructure.candroid"), TABLE, NOW) == Activity.FEED
    assert classify(rep("us.zoom.videomeetings"), TABLE, NOW) == Activity.PET
    assert classify(rep("com.android.chrome"), TABLE, NOW) == Activity.NEUTRAL
    assert classify(None, TABLE, NOW) == Activity.UNKNOWN
    assert classify(rep("com.instagram.android", age=999), TABLE, NOW) == Activity.UNKNOWN
    # screen-off stays valid even when the phone goes quiet (Doze)
    assert classify(rep("", screen=False, age=3600), TABLE, NOW) == Activity.RESTING


def test_doomscrolling_moods_then_death():
    s = PetState(food=100, energy=100, play=100)
    assert s.mood == Mood.HAPPY
    s.tick(13 * 60, Activity.DOOM, NOW)  # -52 health
    assert s.mood == Mood.DIZZY
    s.tick(7 * 60, Activity.DOOM, NOW)
    assert s.mood == Mood.GROGGY
    s.tick(10 * 60, Activity.DOOM, NOW)
    assert s.mood == Mood.DEAD and not s.alive


def test_revive_by_productivity_or_steps():
    s = PetState(health=0, alive=False)
    s.tick(4 * 60, Activity.FEED, NOW)
    assert not s.alive
    s.tick(61, Activity.FEED, NOW)
    assert s.alive and s.mood == Mood.DIZZY

    s2 = PetState(health=0, alive=False)
    s2.apply_steps(1000, NOW)  # baseline
    s2.apply_steps(1600, NOW)
    assert s2.alive


def test_feed_and_pet():
    s = PetState(health=60, food=10, play=10)
    s.tick(5 * 60, Activity.FEED, NOW)
    assert s.food > 30 and s.health > 60
    s.tick(5 * 60, Activity.PET, NOW)
    assert s.play > 30


def test_steps_raise_play_and_handle_reboot():
    s = PetState(play=10)
    assert s.apply_steps(5000, NOW) == 0  # first report is only a baseline
    assert s.apply_steps(6000, NOW) == 1000
    assert s.play == 30
    assert s.apply_steps(100, NOW) == 0  # phone rebooted, counter reset
    assert s.apply_steps(300, NOW) == 200
    assert s.steps_today == 1200


def test_rest_and_sleep_restore_energy():
    s = PetState(energy=10)
    s.update_screen(False, NOW)
    s.tick(60, Activity.RESTING, NOW + 60)
    rest_gain = s.energy - 10
    assert rest_gain > 0 and not s.is_sleeping(NOW + 60)
    later = NOW + SLEEP_AFTER_S + 10
    assert s.is_sleeping(later)
    before = s.energy
    s.tick(60, Activity.RESTING, later)
    assert s.energy - before > rest_gain
    s.update_screen(True, later)
    assert not s.is_sleeping(later)


def test_gaze_cooldown():
    s = PetState(play=50)
    assert s.on_gazed(NOW)
    assert not s.on_gazed(NOW + 1)
    assert s.on_gazed(NOW + 30)
    assert s.play > 50


def test_save_load_roundtrip(tmp_path):
    s = PetState(health=42, food=33)
    p = tmp_path / "state.json"
    s.save(p)
    loaded = PetState.load(p)
    assert abs(loaded.health - 42) < 1 and abs(loaded.food - 33) < 1


def test_animator_all_moods_render():
    a = RavenAnimator(area_width=320)
    for mood in Mood:
        for _ in range(60):
            g = compose(a.update(1 / 12, mood))
            assert len(g) == CANVAS_H and len(g[0]) == CANVAS_W
            assert 0 <= a.x <= 320
    a.start_love()
    hearts = 0
    for _ in range(20):
        hearts += len(a.update(1 / 12, Mood.HAPPY).hearts)
    assert hearts > 0
