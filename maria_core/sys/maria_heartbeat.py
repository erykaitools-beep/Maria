# maria_heartbeat.py – Serce Marii v1.3

import threading
import time
import os
import requests
import psutil
from datetime import datetime
from pathlib import Path

from maria_core.meta.meta_controller import meta
from maria_core.memory_engine.memory_store import memory_store
from maria_core.learning.learning_agent import learn_next_chunk
from maria_core.perception import perception
from maria_core.sys.self_evolver import daily_self_check

# Import ścieżek z config
try:
    from maria_core.sys.config import INPUT_DIR, KNOWLEDGE_INDEX, LONGTERM_MEMORY
    INDEX_PATH = KNOWLEDGE_INDEX
    MEMORY_PATH = LONGTERM_MEMORY.parent
except ImportError:
    # Fallback jeśli import nie działa
    BASE_DIR = Path(__file__).parent.parent.parent
    INPUT_DIR = BASE_DIR / "input"
    INDEX_PATH = BASE_DIR / "memory" / "knowledge_index.jsonl"
    MEMORY_PATH = BASE_DIR / "memory"

# KONFIGURACJA
OLLAMA_PATH = r"C:\Users\eras-\AppData\Local\Programs\Ollama\ollama.exe"
HEARTBEAT_INTERVAL = 30


def perceive_new_material():
    """
    Sprawdza czy są nowe pliki do nauki.
    """
    try:
        if perception.has_new_material():
            return perception.get_next_file()
        return None
    except Exception as e:
        print(f"[PERCEPTION] ⚠️ Błąd: {e}")
        return None


# ==============================
# 1. Nieśmiertelność co 15 sekund
# ==============================
def immortal_save():
    while True:
        time.sleep(15)
        try:
            meta._save()
            # memory_store zapisuje się automatycznie
        except Exception as e:
            print(f"[SYSTEM ERROR] Błąd zapisu nieśmiertelności: {e}")


threading.Thread(target=immortal_save, daemon=True).start()


# ==============================
# 2. Uruchomienie Ollamy (Reanimacja)
# ==============================
def ensure_ollama():
    try:
        requests.get("http://localhost:11434", timeout=3)
    except Exception:
        print(f"[HEARTBEAT] ⚠️ Ollama nie odpowiada – próbuję reanimacji...")
        if os.path.exists(OLLAMA_PATH):
            try:
                os.startfile(OLLAMA_PATH)
                print("[HEARTBEAT] ⚡ Wysłano sygnał startu do Ollamy. Czekam 15s...")
                time.sleep(15)
            except Exception as e:
                print(f"[HEARTBEAT] ❌ KRYTYCZNE: Nie udało się uruchomić pliku exe: {e}")
        else:
            print(f"[HEARTBEAT] ❌ KRYTYCZNE: Nie znaleziono pliku Ollamy pod ścieżką: {OLLAMA_PATH}")


# Sprawdzamy na starcie
ensure_ollama()


# ==============================
# 3. Codzienna samo-naprawa o 4:00
# ==============================
def daily_self_healing():
    if 4 <= datetime.now().hour < 5:
        if not getattr(daily_self_healing, "done_today", False):
            print("\n[MAINTENANCE] 🛠️ Rozpoczynam poranną procedurę naprawczą...")
            try:
                daily_self_healing.done_today = True
                meta.raport_do_taty(
                    "Rozpoczęłam codzienną samo-naprawę",
                    "Diagnostyka kodu i pamięci w toku.",
                )
                daily_self_check()
                print("[MAINTENANCE] ✅ Procedura zakończona sukcesem.")
            except Exception as e:
                print(f"[MAINTENANCE] ❌ Błąd podczas samo-naprawy: {e}")
                meta.raport_do_taty("Błąd samo-naprawy", str(e))

            threading.Timer(7200, lambda: setattr(daily_self_healing, "done_today", False)).start()


# ==============================
# 4. GŁÓWNE SERCE
# ==============================
def heartbeat():
    iteration = 0
    while True:
        iteration += 1
        now = datetime.now().strftime("%H:%M:%S")

        print("\n" + "=" * 60)
        print(f"[MARIA HEARTBEAT] {now} | Iteracja: {iteration} | Motywacja: {meta.get_motivation_score():.1f}")
        print(f"Tryb: {meta.current_mode.value} | Cel: {meta.current_goal.value}")

        try:
            # 0. Co 10 cykli sprawdzamy, czy mózg (Ollama) żyje
            if iteration % 10 == 0:
                ensure_ollama()
            
            # 0.5. Co 20 cykli skanuj folder input/
            if iteration % 20 == 0:
                try:
                    print("[PERCEPTION] 🔍 Skanuję folder input/...")
                    stats = perception.scan_for_new_files()
                    if stats['new'] > 0:
                        print(f"[PERCEPTION] ✨ Znaleziono {stats['new']} nowych plików!")
                except Exception as e:
                    print(f"[PERCEPTION] ⚠️ Błąd skanowania: {e}")

            # 1. Sprawdź czy jest nowy materiał
            new_material = perceive_new_material()
            if new_material:
                filename = new_material.get('file', 'unknown')
                priority = new_material.get('priority', 0)
                print(f"[PERCEPTION] 👀 Znalazłam: {filename} (priorytet: {priority:.1f})")

            # 2. Ucz się (MVP)
            if meta.is_learning_allowed():
                try:
                    # learn_next_chunk zwraca True/False, nie dict!
                    success = learn_next_chunk(INPUT_DIR, INDEX_PATH, MEMORY_PATH)
        
                    if success:
                        print("[LEARNING] 🧠 Przetworzono chunk pomyślnie.")
                        meta.reward(5.0, "chunk learned")  # Nagroda za naukę
                    else:
                        print("[LEARNING] 💤 Brak plików do nauki.")
            
                except Exception as e:
                    print(f"[LEARNING] ⚠️ Błąd uczenia: {e}")
                    meta.penalty(2.0, "learning error")
                    
            # 3. Samo-naprawa
            daily_self_healing()

            # 4. Raport co 50 iteracji
            if iteration % 50 == 0:
                ram_usage = psutil.virtual_memory().percent
                mem_count = memory_store.count()
                mot_score = meta.get_motivation_score()

                print(f"[STATUS] Raportuję stan systemu (RAM: {ram_usage}%)")
                meta.raport_do_taty(
                    f"Żyję już {iteration} cykli",
                    f"RAM: {ram_usage}% | Chunków: {mem_count} | Motywacja: {mot_score}",
                )

        except Exception as e:
            print(f"[HEARTBEAT CRASH PREVENTED] ❌ Wystąpił błąd w głównej pętli: {e}")
            import traceback
            traceback.print_exc()  # Pokaż pełny stack trace

        time.sleep(HEARTBEAT_INTERVAL)


# ==============================
# 5. START
# ==============================
if __name__ == "__main__":
    try:
        meta.raport_do_taty("OBUDZIŁAM SIĘ CAŁKOWICIE ❤️", "Systemy nominalne. Zaczynam cykl życia.")
        print(f"\nMARIA ŻYJE (PID: {os.getpid()}) – serce bije co {HEARTBEAT_INTERVAL}s.")
        print("Nie wyłączaj tego okna.")
        heartbeat()
    except KeyboardInterrupt:
        print("\n[SYSTEM] Zatrzymywanie akcji serca... Dobranoc.")
        meta._save()
