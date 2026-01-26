import os
import shutil
import glob
from datetime import datetime
import requests

from maria_core.agent.interpreter import MEMORY_DIR, LOGS_DIR, log_line
from maria_core.meta.meta_controller import meta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
MAX_LOG_SIZE_MB = 5


def daily_self_check():
    """
    Główna procedura uruchamiana o 4:00 rano przez heartbeat.
    """
    print(f"\n[{datetime.now().strftime('%H:%M')}] 🛡️ URUCHAMIAM PROTOKÓŁ SELF-EVOLVER...")

    # 1. Kopia zapasowa (Safety First)
    _create_backup()

    # 2. Higiena dysku (Logi) – opcjonalnie, ale zostawiamy
    _maintain_logs()

    # 3. Spójność pamięci (Sanity Check)
    health_status = _check_memory_integrity()

    # 4. Refleksja (LLM decyduje o priorytetach na dziś)
    _morning_reflection(health_status)

    print(f"[{datetime.now().strftime('%H:%M')}] ✅ SELF-EVOLVER ZAKOŃCZONY.\n")


def _create_backup():
    """Tworzy zip z folderu pamięci TXT."""
    try:
        if not os.path.exists(BACKUP_DIR):
            os.makedirs(BACKUP_DIR)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        backup_name = os.path.join(BACKUP_DIR, f"memory_backup_{timestamp}")

        if os.path.exists(MEMORY_DIR):
            shutil.make_archive(backup_name, "zip", MEMORY_DIR)
            print(f"[EVOLVER] 💾 Wykonano backup pamięci: {backup_name}.zip")

            # Usuwamy stare backupy (zostawiamy 7 ostatnich)
            backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "*.zip")))
            while len(backups) > 7:
                old = backups.pop(0)
                os.remove(old)
                print(f"[EVOLVER] 🗑️ Usunięto stary backup: {old}")
        else:
            print(f"[EVOLVER] ⚠️ Nie znaleziono katalogu {MEMORY_DIR} do backupu!")

    except Exception as e:
        print(f"[EVOLVER] ❌ Błąd backupu: {e}")


def _current_log_file():
    today = datetime.now().date().strftime("%Y_%m_%d")
    return os.path.join(LOGS_DIR, f"log_{today}.txt")


def _maintain_logs():
    """Archiwizuje dzisiejszy log, jeśli jest za duży."""
    try:
        log_file = _current_log_file()
        if os.path.exists(log_file):
            size_mb = os.path.getsize(log_file) / (1024 * 1024)
            if size_mb > MAX_LOG_SIZE_MB:
                timestamp = datetime.now().strftime("%Y%m%d")
                archive_dir = os.path.join(BASE_DIR, "logs_archive")
                if not os.path.exists(archive_dir):
                    os.makedirs(archive_dir)
                new_name = os.path.join(archive_dir, f"maria_log_{timestamp}.txt")
                shutil.move(log_file, new_name)
                with open(log_file, "w", encoding="utf-8") as f:
                    f.write(f"--- NOWY LOG ROZPOCZĘTY: {datetime.now()} ---\n")
                print(f"[EVOLVER] 📜 Zarchiwizowano logi ({size_mb:.2f} MB). Czysta karta.")
    except Exception as e:
        print(f"[EVOLVER] ⚠️ Błąd przy logach: {e}")


def _check_memory_integrity():
    """
    MVP: dla Twojej struktury (TXT) tylko sprawdzamy, ile jest plików.
    Nie bawimy się w JSON-y, bo ich nie używasz.
    """
    if not os.path.exists(MEMORY_DIR):
        return "Brak katalogu pamięci."

    files = [f for f in os.listdir(MEMORY_DIR) if f.endswith(".txt")]
    return f"Pamięć TXT wygląda OK. Liczba rekordów: {len(files)}"


def _morning_reflection(health_status: str):
    """
    Maria pyta sama siebie (LLM), jaki tryb przyjąć na nowy dzień.
    """
    prompt = f"""
Jest 4:00 rano. Robisz przegląd systemów.
Status techniczny: {health_status}
Twoja obecna motywacja: {meta.get_motivation_score()}
Twój obecny cel: "{meta.current_goal.value}"

Jako autonomiczna AI, zdecyduj krótko (jedno zdanie, po polsku):
Na czym skupisz się w nadchodzącym dniu? Czy zmieniasz cel?
"""

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3.2:3b",  # zaktualizuj model
                "prompt": prompt,
                "stream": False,
            },
            timeout=30,
        )

        if response.status_code == 200:
            result = response.json().get("response", "").strip()
            print(f"[EVOLVER] 🧠 Poranna refleksja: {result}")
            
            # Użyj nowej metody update_goal zamiast nieistniejącej
            meta.update_goal(result)
            
            # Wyślij raport
            meta.raport_do_taty(
                "Poranny Raport Stanu 🌅",
                f"**Status techniczny:** {health_status}\n"
                f"**Motywacja:** {meta.get_motivation_score()}\n"
                f"**Plan na dziś:** {result}\n"
                f"**Uptime:** {meta.state['total_uptime_hours']:.1f}h"
            )
        else:
            print(f"[EVOLVER] ⚠️ Ollama odpowiedziała kodem {response.status_code}")
            meta.raport_do_taty("Błąd porannej refleksji", f"Ollama: status {response.status_code}")

    except Exception as e:
        print(f"[EVOLVER] ⚠️ Nie udało się przeprowadzić refleksji: {e}")
        meta.raport_do_taty("Błąd porannej refleksji", str(e))
if __name__ == "__main__":
    daily_self_check()
