#!/usr/bin/env bash
#
# disable_suspend.sh — stop the Mini PC from ever suspending.
#
# WHY: On 2026-06-02 and 2026-06-03 the machine logged "Suspend key pressed"
# (a phantom KEY_SLEEP HID event, most likely from the Innomaker camera which
# registers as a keyboard, or the Cherry USB keyboard) and dropped to S3 deep
# sleep for ~12h each morning. Maria's tick loop "froze" only because the whole
# CPU was halted — no software watchdog can catch that. This server must never
# sleep. Two layers, belt + suspenders:
#   1. logind ignores the suspend/power/hibernate keys  (stops the trigger)
#   2. mask the sleep targets                            (suspend made impossible)
#
# RUN AS ROOT:  sudo bash /home/maria/maria/scripts/disable_suspend.sh
# REVERT:       see the commented block at the bottom.
#
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "ERROR: must run as root.  Try:  sudo bash $0" >&2
    exit 1
fi

echo "==> Layer 1: tell systemd-logind to ignore power/sleep keys"
install -d -m 0755 /etc/systemd/logind.conf.d
cat > /etc/systemd/logind.conf.d/no-suspend.conf <<'EOF'
# Headless server: never act on a (phantom) power/sleep/hibernate key.
# Added 2026-06-03 after two days of spurious S3 suspends. See
# scripts/disable_suspend.sh for context.
[Login]
HandleSuspendKey=ignore
HandlePowerKey=ignore
HandleHibernateKey=ignore
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
EOF
systemctl restart systemd-logind
echo "    logind drop-in written and service restarted."

echo "==> Layer 2: mask the sleep targets (suspend physically impossible)"
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target

echo
echo "==> Verification"
echo -n "    suspend.target  : "; systemctl is-enabled suspend.target 2>/dev/null || true
echo -n "    sleep.target    : "; systemctl is-enabled sleep.target 2>/dev/null || true
echo -n "    hibernate.target: "; systemctl is-enabled hibernate.target 2>/dev/null || true
echo "    logind HandleSuspendKey:"
grep -i HandleSuspendKey /etc/systemd/logind.conf.d/no-suspend.conf | sed 's/^/      /'
echo
echo "    Live check (deterministic state — no suspend is actually invoked):"
all_masked=1
for t in suspend.target sleep.target hibernate.target hybrid-sleep.target; do
    [[ "$(systemctl is-enabled "$t" 2>/dev/null)" == "masked" ]] || all_masked=0
done
hsk=$(busctl get-property org.freedesktop.login1 /org/freedesktop/login1 \
        org.freedesktop.login1.Manager HandleSuspendKey 2>/dev/null || true)
if [[ "${all_masked}" -eq 1 && "${hsk}" == *ignore* ]]; then
    echo "      OK — all sleep targets masked AND logind ignores the suspend key."
    echo "      Any suspend request now logs: 'Unit suspend.target is masked, refusing operation'."
else
    echo "      WARN — expected all-masked + HandleSuspendKey=ignore; review output above." >&2
fi

echo
echo "DONE. The machine can no longer suspend. No daemon restart needed —"
echo "this is OS-level config and takes effect immediately."

# ─────────────────────────────────────────────────────────────────────────
# TO REVERT (if ever needed):
#   sudo systemctl unmask sleep.target suspend.target hibernate.target hybrid-sleep.target
#   sudo rm /etc/systemd/logind.conf.d/no-suspend.conf
#   sudo systemctl restart systemd-logind
# ─────────────────────────────────────────────────────────────────────────
