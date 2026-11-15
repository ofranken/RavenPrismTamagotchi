#!/usr/bin/env bash
# Keep the phone -> simulator USB tunnel alive.
# `adb reverse` is wiped whenever adb or the USB connection restarts, which makes the
# phone app fail with "Failed to connect to 127.0.0.1:8765". This re-applies it every 3 s.
PORT="${RAVEN_PET_PORT:-8765}"
echo "keeping adb reverse tcp:$PORT alive (Ctrl+C to stop)"
while true; do
    if ! adb reverse --list 2>/dev/null | grep -q "tcp:$PORT"; then
        adb wait-for-device 2>/dev/null
        adb reverse "tcp:$PORT" "tcp:$PORT" >/dev/null 2>&1 && echo "$(date +%T) tunnel restored"
    fi
    sleep 3
done
