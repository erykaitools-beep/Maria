import os
import datetime

# Ścieżka do Twojego systemu AI
BASE_DIR = r"Moja AI - Maria Ver.1"
MEMORY_DIR = os.path.join(BASE_DIR, "memory")
LINKS_DIR = os.path.join(BASE_DIR, "links")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
STATE_DIR = os.path.join(BASE_DIR, "state")

def next_memory_number():
    files = [f for f in os.listdir(MEMORY_DIR) if f.endswith(".txt")]
    if not files:
        return 1
    numbers = [int(f.split(".")[0]) for f in files]
    return max(numbers) + 1

def write_log(text):
    log_file = os.path.join(LOGS_DIR, "log_2025_11_24.txt")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(text + "\n")

def update_state():
    now = datetime.datetime.now()
    state_file = os.path.join(STATE_DIR, "current.txt")
    with open(state_file, "w", encoding="utf-8") as f:
        f.write(f"czas: {now.strftime('%Y-%m-%d %H:%M')}\n")
        f.write("stan: 'zapis_pamieci'\n")
        f.write("kontekst: 'dodano nowy rekord pamięci'\n")
        f.write("energia: 90\n")
        f.write("uwaga: 'normalna'\n")

def create_memory():
    now = datetime.datetime.now()
    mem_number = next_memory_number()
    filename = f"{mem_number:03}.txt"
    file_path = os.path.join(MEMORY_DIR, filename)

    print("\nCo chcesz zapisać w pamięci AI?")
    content = input("Treść: ")

    print("Dlaczego to jest ważne?")
    reason = input("Dlaczego: ")

    print("Podaj powiązania (po przecinku):")
    links_raw = input("Powiązania: ")
    links = [x.strip() for x in links_raw.split(",")]

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(f"czas: {now.strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"treść: \"{content}\"\n")
        f.write(f"dlaczego: \"{reason}\"\n")
        f.write(f"powiązania: {links}\n")
        f.write(f"priorytet: 5\n")

    # mapa powiązań
    map_file = os.path.join(LINKS_DIR, f"{mem_number:03}_map.txt")
    with open(map_file, "w", encoding="utf-8") as f:
        for link in links:
            f.write(f"{mem_number:03} -> {link}\n")

    # log
    write_log(f"[{now.strftime('%H:%M')}] Dodano rekord pamięci ({filename})")
    
    # update state
    update_state()

    print("\n✅ Pamięć zapisana!")
    print(f"➡ {filename}")
    print(f"➡ mapa: {mem_number:03}_map.txt\n")

# uruchomienie
create_memory()
