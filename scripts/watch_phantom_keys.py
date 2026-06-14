#!/usr/bin/env python3
"""
watch_phantom_keys.py — catch the phantom power/sleep/suspend key and name its device.

WHY: On 2026-06-02/03 the Mini PC suspended to S3 on a phantom "Suspend key
pressed" (see scripts/disable_suspend.sh). The Innomaker camera (which oddly
registered as a keyboard) was the prime suspect and has been unplugged — but the
Cherry USB keyboard ALSO reports KEY_SLEEP capability, so it cannot be ruled out
by elimination. This monitor reads raw input events from every /dev/input/event*
at once and logs any KEY_POWER / KEY_SLEEP / KEY_SUSPEND press together with the
exact source device, so the next phantom event identifies the culprit.

No external dependencies (pure struct/select). Needs root to read /dev/input.

    sudo python3 /home/maria/maria/scripts/watch_phantom_keys.py

Leave it running (e.g. inside zellij/tmux, or `nohup sudo python3 ... &`).
Events print live AND append to meta_data/phantom_keys.log. Ctrl-C to stop.

INTERPRETATION after leaving it overnight:
  * a KEY_SLEEP from the Cherry keyboard  -> the keyboard misfires too (replace it)
  * nothing logged                        -> the camera was the culprit, case closed
"""
import glob
import os
import select
import struct
import sys
import time

# struct input_event on 64-bit Linux: timeval(2x long=16B) + u16 type + u16 code + s32 value
EV_FORMAT = "llHHi"
EV_SIZE = struct.calcsize(EV_FORMAT)  # 24
EV_KEY = 0x01
WATCH = {
    116: "KEY_POWER",
    142: "KEY_SLEEP(=suspend key)",
    143: "KEY_WAKEUP",
    205: "KEY_SUSPEND(=hibernate)",
}
VALUE = {0: "release", 1: "PRESS", 2: "repeat"}

LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "meta_data", "phantom_keys.log"
)


def dev_name(path: str) -> str:
    node = os.path.basename(path)
    try:
        with open(f"/sys/class/input/{node}/device/name") as f:
            return f.read().strip()
    except OSError:
        return "?"


def main() -> None:
    fds = {}
    for p in sorted(glob.glob("/dev/input/event*")):
        try:
            fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = (p, dev_name(p))
        except OSError as e:
            print(f"  skip {p}: {e}", file=sys.stderr)
    if not fds:
        print("No readable /dev/input/event* — run with sudo.", file=sys.stderr)
        sys.exit(1)

    print(f"Watching {len(fds)} input devices for power/sleep/suspend keys. Ctrl-C to stop.")
    for _, (p, n) in sorted(fds.items()):
        print(f"  {p}  {n}")
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

    while True:
        ready, _, _ = select.select(list(fds), [], [])
        for fd in ready:
            try:
                data = os.read(fd, EV_SIZE * 64)
            except OSError:
                continue
            for off in range(0, len(data) - EV_SIZE + 1, EV_SIZE):
                _, _, etype, code, value = struct.unpack(EV_FORMAT, data[off : off + EV_SIZE])
                if etype == EV_KEY and code in WATCH and value in (1, 2):
                    p, n = fds[fd]
                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    msg = f"{ts}  {WATCH[code]:<24} {VALUE.get(value, value):<7} <- {n} [{p}]"
                    print(msg, flush=True)
                    try:
                        with open(LOG_PATH, "a") as f:
                            f.write(msg + "\n")
                    except OSError:
                        pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nstopped.")
