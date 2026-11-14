# Raven Pet: a tamagotchi raven for Raven Prism

A fat, pixel-art raven (modelled on the Raven plush in `art/`) lives on your Raven Prism glasses
and reacts to how you use your phone.

| Stat | Goes up when… | Goes down when… |
|---|---|---|
| ❤ **Health** | productive apps, sleep, looking at the raven, walking | doomscrolling, any other stat hits 0 |
| 🍒 **Food** | Email / Gmail / Outlook / Canvas are open | slowly over time |
| ⚡ **Energy** (tired) | phone screen off (rest); 30+ min screen-off = **sleep** (much faster) | phone in use, doomscrolling |
| 👣 **Play** | **walking** (phone step counter), Zoom calls, looking at the raven | slowly over time |

**Penalty apps:** Instagram, TikTok, X, Facebook.

**How the raven looks at each health level**
- **> 50%:** happy. Hops around and flaps its wings.
- **≤ 50%:** brain fog. Dizzy with stars spinning around its head.
- **≤ 25%:** walks groggily, dragging its wings, stars still spinning.
- **0%:** dead. On its back with X eyes. You revive it with 5 minutes of productive apps or 500 steps.
- **Low energy, or you're asleep:** it sleeps with Z's floating up.
- **When you look at it** (eye gaze; mouse in the simulator), it plays a happy animation with hearts.

## Layout

```
raven_pet/        Raven Prism app (Python, Raven Framework)
  main.py           app entry point: UI, gaze, game loop, simulator keys
  pet_state.py      stats, rules, app categories, save/load (pure Python)
  animator.py       behaviour state machine → poses (pure Python)
  pixel_art.py      procedural pixel-art raven + particles (pure Python)
  phone_link.py     HTTP server for the phone + UDP discovery beacon
  tests/            pytest suite
  tools/render_preview.py   renders a PNG contact sheet of all poses
android/          Companion app for the Pixel (Kotlin, no external libraries)
```

## Run the glasses app

```bash
python3 -m venv .venv
.venv/bin/pip install -e raven-framework-main/raven-framework-main
cd raven_pet
../.venv/bin/python main.py           # simulator
../.venv/bin/python main.py deploy    # to the glasses (set APP_ID / APP_KEY in main.py first)
```

Simulator keys: `1` Instagram · `2` Gmail · `3` Zoom · `4` other app · `5` screen off · `6` asleep ·
`0` no phone · `W` +250 steps · `L` love · `F` 60× speed · `D` −25 health · `R` reset.

Environment variables: `RAVEN_PET_SPEED` (time multiplier for demos), `RAVEN_PET_PORT` (default 8765),
`RAVEN_PET_STATE` (save file, default `~/.local/share/raven_pet/state.json`),
`RAVEN_PET_PAIR` (optional code the phone must send in `X-Raven-Pair`).

To change which apps count as penalty, feed or pet, create `raven_pet/categories.json`:
`{"doom": ["com.instagram.android", ...], "feed": [...], "pet": [...]}`

Tests: `cd raven_pet && ../.venv/bin/python -m pytest -q tests`

## Run the phone app

```bash
cd android
./gradlew assembleDebug        # needs JDK 17-21 and the Android SDK (local.properties → sdk.dir)
adb install -r -g app/build/outputs/apk/debug/app-debug.apk
```

On the phone: open **Raven Pet**, tap **Grant usage access** and enable it for Raven Pet, allow step
tracking, then tap **Start sending to Raven**. It finds the glasses automatically on the same Wi-Fi
(UDP beacon on port 47800). You can also type the glasses' IP, which the glasses show on screen until a phone connects.

For testing against the desktop simulator over USB:
`adb reverse tcp:8765 tcp:8765`, then set the glasses address to `127.0.0.1`.

### Protocol

`POST http://<glasses>:8765/activity`
```json
{"package": "com.instagram.android", "label": "Instagram", "screen_on": true, "steps_total": 12345}
```
Sent every 5 s, and immediately when the foreground app or screen state changes. The response (and
`GET /status`) is the raven's stats:
`{"health": 72.0, "food": 80.1, "energy": 64.3, "play": 55.0, "mood": "happy", "activity": "doom", ...}`

## Notes and limits
- On the glasses' additive display pure black is invisible, so the "black" raven is drawn in deep indigo with a lavender rim.
- Only apps are detected. Instagram or X opened in a web browser shows up as the browser (neutral).
- The link is plain HTTP on the local network with no authentication unless you set `RAVEN_PET_PAIR`.
