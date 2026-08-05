"""
Model warm-up - rozgrzewa lokalne modele Ollama przy starcie demona.

Problem (cold-start exam waste, 2026-06-04): po restarcie demona (lub po >30m
przerwy gdy Ollama wyladowala model na keep_alive) PIERWSZY egzamin platil pelny
cold-start. Pomiar 2026-06-04 pokazal, ze samo zaladowanie wag to ~3s -- prawdziwy
koszt to WOLNA PIERWSZA INFERENCJA na zimnym CPU (4096 tokenow, governor w
powersave, kontencja z indekserem) -> timeout 240s, retry na rozgrzanym przeszedl.
Efekt: ~8 min zmarnowane na pierwszym egzaminie po starcie (dwa kroki student+grade,
kazdy timeout raz, potem sukces "warm").

b12dd7f mylnie nazwano "warm-pin": dal tylko keep_alive=30m (model zostaje w RAM
PO zaladowaniu), ale nie laduje modelu proaktywnie -- po dlugiej przerwie i tak
cold-startuje.

Fix historyczny rozgrzewal oba modele egzaminacyjne. Po incydencie termicznym
2026-08-05 startup moze wykonac MALA REALNA generacje tylko na jednym modelu
(student=llama3.1), i tylko gdy prawdziwy czujnik temperatury oraz CPU wskazuja
bezpieczny stan. Grader qwen3 rozgrzewa sie na zadanie przez wspolna bramke CPU.
Pusty-promptowy preload (done_reason=load) NIE wystarcza -- nie wykonuje
forward-pass, wiec nie rozgrzewa sciezki inferencji.

Wywolanie jest anulowalne miedzy zadaniami, serializowane z tekstem, vision i
bge-m3 oraz bounded przez shared client (httpx read-timeout) + call_with_timeout.
"""

import logging
import os
import threading
import time
from typing import Callable, Dict, List, Optional

import psutil

from .execution_budget import call_with_timeout, get_ollama_client
from .local_compute import (
    LocalComputeBlocked,
    get_local_compute_coordinator,
)

try:
    from maria_core.sys.config import OLLAMA_KEEP_ALIVE as _DEFAULT_KEEP_ALIVE
except Exception:
    _DEFAULT_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")

logger = logging.getLogger(__name__)


# Startup may warm at most one 8B model automatically.  Warming both the student
# and grader before any real work was the boot-time heat source; qwen3 now warms
# on demand through the shared local-compute gate.
DEFAULT_WARMUP_MODELS = ["llama3.1:8b"]

# Krotka generacja wystarczy do rozgrzania compute path; nie potrzeba pelnego
# kontekstu egzaminu (KV-cache alokacja to nie glowny koszt cold-startu).
_WARMUP_PROMPT = "Reply with the single word OK."
_WARMUP_NUM_PREDICT = 16

# Bounded per-model. Cold load+gen na cieplym dysku to ~4s; po reboocie maszyny
# (zimny cache dysku) moze byc wolniej. 120s = z duzym marginesem, ale wciaz
# 6x mniej niz obecny 240sx3 cold-exam waste, ktory to naprawia.
_WARMUP_TIMEOUT_S = 120.0

# Delay przed rozgrzaniem: pozwala homeostazie sie ustabilizowac, ale jest
# krotszy niz indekser (60s), zeby modele byly cieple zanim ruszy ciezki embed
# i zanim operator wysle /teacher zaraz po /restart.
STARTUP_DELAY_SEC = 30
STARTUP_CPU_LIMIT_PCT = 50.0


def warm_up_models(
    model_tags: Optional[List[str]] = None,
    keep_alive: str = _DEFAULT_KEEP_ALIVE,
    num_predict: int = _WARMUP_NUM_PREDICT,
    prompt: str = _WARMUP_PROMPT,
    timeout_s: float = _WARMUP_TIMEOUT_S,
    cancel_event: Optional[threading.Event] = None,
) -> Dict[str, Dict]:
    """Rozgrzej podane modele jedna mala generacja kazdy (sekwencyjnie).

    Wykonuje realny generate (nie pusty preload), zeby rozgrzac wagi + compute
    kernels + CPU governor. keep_alive trzyma model w RAM po rozgrzaniu, tak ze
    pierwszy prawdziwy egzamin nie cold-startuje.

    Bledy per-model sa izolowane: timeout/blad jednego modelu nie przerywa
    rozgrzewania pozostalych.

    Args:
        model_tags: tagi Ollama do rozgrzania (default: student + grader).
        keep_alive: jak dlugo Ollama trzyma model po rozgrzaniu.
        num_predict: ile tokenow wygenerowac (16 wystarcza do rozgrzania).
        prompt: krotki prompt rozgrzewajacy.
        timeout_s: bounded deadline per model.

    Returns:
        Mapa tag -> {"ok": bool, "latency_s": float, "error": Optional[str]}.
    """
    if model_tags is None:
        model_tags = DEFAULT_WARMUP_MODELS

    results: Dict[str, Dict] = {}
    coordinator = get_local_compute_coordinator()

    client = get_ollama_client()
    if client is None:
        logger.warning("[WARMUP] ollama library unavailable -- skipping warm-up")
        for tag in model_tags:
            results[tag] = {"ok": False, "latency_s": 0.0, "error": "no ollama client"}
        return results

    for tag in model_tags:
        if cancel_event is not None and cancel_event.is_set():
            results[tag] = {
                "ok": False, "latency_s": 0.0, "error": "cancelled",
                "cancelled": True,
            }
            continue
        start = time.time()
        try:
            def _generate(t=tag):
                with coordinator.lease(
                    "warmup", model=t, timeout_s=timeout_s,
                    cancel_event=cancel_event,
                ):
                    return client.generate(
                        model=t,
                        prompt=prompt,
                        stream=False,
                        keep_alive=keep_alive,
                        options={"num_predict": num_predict},
                    )

            call_with_timeout(
                _generate,
                timeout_sec=timeout_s,
                label=f"warmup {tag}",
            )
            latency = time.time() - start
            if cancel_event is not None and cancel_event.is_set():
                results[tag] = {
                    "ok": False, "latency_s": latency, "error": "cancelled",
                    "cancelled": True,
                }
                continue
            results[tag] = {"ok": True, "latency_s": latency, "error": None}
            logger.info(f"[WARMUP] {tag} warmed in {latency:.1f}s (keep_alive={keep_alive})")
        except LocalComputeBlocked as e:
            latency = time.time() - start
            results[tag] = {
                "ok": False, "latency_s": latency, "error": str(e),
                "cancelled": True,
            }
            logger.info("[WARMUP] %s blocked: %s", tag, e)
        except Exception as e:
            latency = time.time() - start
            results[tag] = {"ok": False, "latency_s": latency, "error": str(e)}
            # Nie przerywaj -- kolejny model i tak warto rozgrzac.
            logger.warning(f"[WARMUP] {tag} failed after {latency:.1f}s: {e}")

    ok = sum(1 for r in results.values() if r["ok"])
    logger.info(f"[WARMUP] Done: {ok}/{len(model_tags)} models warm")
    return results


def start_background_warmup(
    model_tags: Optional[List[str]] = None,
    delay_sec: float = STARTUP_DELAY_SEC,
    keep_alive: str = _DEFAULT_KEEP_ALIVE,
    startup_cpu_limit_pct: float = STARTUP_CPU_LIMIT_PCT,
    cpu_percent_fn: Optional[Callable[[], float]] = None,
) -> Optional[threading.Thread]:
    """Rozgrzej modele w wątku w tle po delayu. Zwraca wątek (lub None gdy off).

    Sterowane przez ENV:
      - MARIA_WARMUP=0     -> wylacz calkowicie (zwraca None)
      - MARIA_WARMUP_MODELS=tag1,tag2 -> wybierz modele (startup bierze pierwszy)
      - MARIA_WARMUP_DELAY=N -> nadpisz delay (sekundy)

    Wzorzec jak start_background_indexing: daemon thread, delay na CPU-cooldown.
    """
    if os.environ.get("MARIA_WARMUP", "1") == "0":
        logger.info("[WARMUP] disabled via MARIA_WARMUP=0")
        return None

    env_models = os.environ.get("MARIA_WARMUP_MODELS")
    if env_models:
        model_tags = [t.strip() for t in env_models.split(",") if t.strip()]
    elif model_tags is None:
        model_tags = DEFAULT_WARMUP_MODELS

    if model_tags and len(model_tags) > 1:
        logger.warning(
            "[WARMUP] Startup is limited to one model; ignoring %s",
            model_tags[1:],
        )
        model_tags = model_tags[:1]

    env_delay = os.environ.get("MARIA_WARMUP_DELAY")
    if env_delay:
        try:
            delay_sec = float(env_delay)
        except ValueError:
            pass

    coordinator = get_local_compute_coordinator()
    cancel_event = threading.Event()
    token = coordinator.register_background_task(
        "model-warmup",
        cancel_event.set,
        cancel_on_nim_exhausted=True,
    )

    def _run():
        try:
            if delay_sec > 0:
                logger.info(f"[WARMUP] Waiting {delay_sec:.0f}s before warm-up (CPU cooldown)")
                if cancel_event.wait(delay_sec):
                    logger.info("[WARMUP] Cancelled during startup delay")
                    return
            coordinator.verify_startup_temperature()
            if not coordinator.startup_background_allowed():
                logger.info("[WARMUP] Skipped: thermal/NIM backoff active")
                return
            read_cpu = cpu_percent_fn or (lambda: psutil.cpu_percent(interval=0.1))
            cpu_load = float(read_cpu())
            if cpu_load >= startup_cpu_limit_pct:
                logger.warning(
                    "[WARMUP] Skipped: CPU already busy (%.1f%% >= %.1f%%)",
                    cpu_load, startup_cpu_limit_pct,
                )
                return
            warm_up_models(
                model_tags=model_tags,
                keep_alive=keep_alive,
                cancel_event=cancel_event,
            )
        except Exception as e:
            logger.error(f"[WARMUP] Background warm-up failed: {e}")
        finally:
            coordinator.unregister_background_task(token)

    t = threading.Thread(target=_run, name="model-warmup", daemon=True)
    t.cancel_event = cancel_event
    t.compute_task_token = token
    t.start()
    logger.info(f"[WARMUP] Background warm-up started (models={model_tags})")
    return t
