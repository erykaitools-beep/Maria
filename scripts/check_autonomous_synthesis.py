#!/usr/bin/env python3
"""Watcher: did Maria's autonomous synthesis picker FIRE ON ITS OWN.

Runs from cron on the mini PC (Mon-Fri after the learning windows), so it
works whether or not any laptop / Claude session is up. Idempotent: pings
Telegram only when a NEW ``autonomous_synthesis`` event appears since the
last notification, then advances a marker. Zero dependency on the live
daemon -- it just reads the append-only event log.

Judgement note baked into the message: the synthesis exam is a closed loop
(author + grader share the NIM family), so a high score is NOT proof of
correctness. The real guard is the faithfulness gate (independent qwen3:
claims-vs-sources). The message surfaces faithfulness, not just the score.
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path("/home/maria/maria")
META = ROOT / "meta_data"
EVENTS = META / "homeostasis_events.jsonl"
REVIEW = META / "synthesis_review.jsonl"
PICKER_STATE = META / "synthesis_picker_state.json"
MARKER = META / ".synth_autocheck_notified"
LOG = META / "synth_autocheck.log"
ENV = ROOT / ".env"


def load_env():
    out = {}
    try:
        for line in ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            out[key.strip()] = val.strip()
    except OSError:
        pass
    return out


def read_jsonl(path):
    recs = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return recs


def send_telegram(text):
    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN")
    chat = env.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    url = "https://api.telegram.org/bot%s/sendMessage" % token
    try:
        urllib.request.urlopen(
            urllib.request.Request(url, data=data), timeout=15
        )
        return True
    except Exception:
        return False


def _ts(rec):
    try:
        return float(rec.get("timestamp", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _match_review(reviews, file_id):
    """The synthesis_review row for THIS autonomous run.

    Match by file_id so a later manual /synthesize cannot hijack the verdict
    shown for the autonomous run (the old code took reviews[-1] blindly).
    Falls back to the newest row when the id is missing/unmatched -- a
    best-effort verdict beats none.
    """
    if not reviews:
        return None
    if file_id:
        for rec in reversed(reviews):
            if rec.get("file_id") == file_id:
                return rec
    return reviews[-1]


# Faithfulness reasons that mean the JUDGE COULD NOT RUN (infra), NOT that the
# synthesis was unfaithful. They surface as 0/N supported with 0 contradicted,
# which reads exactly like a bad synthesis unless the message says otherwise.
# This is the Monday-legibility fix: a judge stall must never masquerade as a
# content verdict.
# Standalone copy ON PURPOSE: this watcher is zero-import (stdlib only) so it
# runs from bare cron without the daemon's pythonpath. CANONICAL SOURCE is
# agent_core.synthesis.JUDGE_STALL_REASONS -- keep the two in sync.
_JUDGE_STALL_REASONS = {
    "judge_failed", "judge_parse_failed", "no_material_or_claims",
}


def _faith_note(fz):
    """(human faithfulness line, judge_stalled?) for a review's verdict dict.

    Distinguishes a judge STALL (timeout/parse error -- no real signal) from an
    actual SUPPORTED/CONTRADICTED verdict. Returns ("", False) when no verdict
    is available (no judge wired)."""
    if not isinstance(fz, dict):
        return "", False
    reason = str(fz.get("reason") or "")
    if reason in _JUDGE_STALL_REASONS:
        return (
            " | UWAGA: sedzia wiernosci NIE ZADZIALAL (%s) -- to NIE ocena "
            "syntezy, tylko timeout/blad lokalnego qwen3 na CPU. Brak realnego "
            "sygnalu wiernosci." % reason,
            True,
        )
    return (
        " | wiernosc %s/%s (sprzeczne %s; reason=%s)" % (
            fz.get("supported", "?"), fz.get("total", "?"),
            fz.get("contradicted", "?"), reason or "?",
        ),
        False,
    )


def build_message(latest, fz, new_count, total_count):
    """Compose the Telegram message for a fired autonomous synthesis.

    Pure (no I/O) so it is unit-testable; all I/O stays in main(). ``fz`` is the
    matched review's ``faithfulness`` dict (or None)."""
    topic = latest.get("topic")
    promoted = latest.get("promoted")
    success = latest.get("success")
    reason = latest.get("reason")
    exam = latest.get("exam") if isinstance(latest.get("exam"), dict) else {}
    score = exam.get("score")
    passed = exam.get("passed")

    faith, judge_stalled = _faith_note(fz)

    if judge_stalled:
        verdict_line = (
            "Ocena: sedzia sie zadlawil -> to problem INFRY (budzet/CPU), nie "
            "tresci. Powtorz /synthesize na luznym boxie albo podnies budzet "
            "sedziego -- NIE oceniaj tej syntezy."
        )
    else:
        verdict_line = (
            "Ocena: patrz na WIERNOSC + tresc, nie sam score. Zla -> "
            "/retract /quarantine /forget_source"
        )

    return (
        "[Maria] POPLYNELA SAMA: autonomiczna synteza odpalila sie z wlasnej "
        "woli.\n"
        "temat: %s\n"
        "egzamin: %s score=%s%s\n"
        "promoted (do produkcji): %s | success: %s%s\n"
        "(%d nowych od ostatniego checku; total %d)\n"
        "%s"
        % (
            topic,
            "pass" if passed else "fail",
            score,
            faith,
            promoted,
            success,
            (" reason=%s" % reason) if reason else "",
            new_count,
            total_count,
            verdict_line,
        )
    )


def main():
    events = read_jsonl(EVENTS)
    autos = [
        e for e in events
        if e.get("event") == "autonomous_synthesis"
        or e.get("event_type") == "autonomous_synthesis"
    ]

    last_notified = 0.0
    try:
        last_notified = float(MARKER.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pass

    new_autos = [e for e in autos if _ts(e) > last_notified]
    stamp = time.strftime("%Y-%m-%d %H:%M")

    if not new_autos:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(
                "%s brak nowych autonomous_synthesis (total=%d, picker_state=%s)\n"
                % (stamp, len(autos), PICKER_STATE.exists())
            )
        return

    latest = max(new_autos, key=_ts)
    topic = latest.get("topic")
    promoted = latest.get("promoted")

    # Faithfulness from the review row that MATCHES this run (by file_id) --
    # so a judge stall is shown as infra, not as a bad-synthesis verdict.
    reviews = read_jsonl(REVIEW)
    matched = _match_review(reviews, latest.get("file_id"))
    fz = matched.get("faithfulness") if isinstance(matched, dict) else None
    msg = build_message(latest, fz, len(new_autos), len(autos))

    sent = send_telegram(msg)
    try:
        MARKER.write_text(str(max(_ts(e) for e in new_autos)), encoding="utf-8")
    except OSError:
        pass
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(
            "%s NOWE autonomous_synthesis x%d topic=%s promoted=%s telegram_sent=%s\n"
            % (stamp, len(new_autos), topic, promoted, sent)
        )


if __name__ == "__main__":
    main()
