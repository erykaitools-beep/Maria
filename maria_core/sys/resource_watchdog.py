# resource_watchdog.py
# Prosty watchdog RAM dla M.A.R.I.I

import threading
import time
import os
import logging

import psutil


def _watch_ram_loop(
    limit_percent: int = 80,
    check_interval_sec: int = 3,
):
    logger = logging.getLogger("RAM_WATCHDOG")
    logger.info(
        f"[WATCHDOG] Start RAM watcher (limit={limit_percent}%, interval={check_interval_sec}s)"
    )

    while True:
        mem = psutil.virtual_memory()
        if mem.percent >= limit_percent:
            logger.error(
                f"[WATCHDOG] RAM {mem.percent:.1f}% >= {limit_percent}%. "
                f"Zatrzymuję proces M.A.R.I.A., żeby nie ubić całego systemu."
            )
            # Twardy bezpiecznik – natychmiastowe wyjście z procesu
            os._exit(1)

        time.sleep(check_interval_sec)


def start_watchdog(
    limit_percent: int = 80,
    check_interval_sec: int = 3,
):
    """
    Uruchamia w tle wątek pilnujący RAM. Jeśli próg zostanie przekroczony,
    proces jest natychmiast ubijany.
    """
    t = threading.Thread(
        target=_watch_ram_loop,
        args=(limit_percent, check_interval_sec),
        daemon=True,
    )
    t.start()
    return t
