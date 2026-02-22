import os
import sys
import datetime

from maria_core.memory_engine.semantic.semantic_bridge import remember_fact, query_related

# Bazowy folder - tam, gdzie leży ten plik
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(BASE_DIR, "memory")
LINKS_DIR = os.path.join(BASE_DIR, "links")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
STATE_DIR = os.path.join(BASE_DIR, "state")
GOALS_DIR = os.path.join(BASE_DIR, "goals")

def ensure_dirs():
    for d in [MEMORY_DIR, LINKS_DIR, LOGS_DIR, STATE_DIR, GOALS_DIR]:
        if not os.path.isdir(d):
            os.makedirs(d)

def next_memory_number():
    files = [f for f in os.listdir(MEMORY_DIR) if f.endswith(".txt")]
    if not files:
        return 1
    numbers = []
    for f in files:
        try:
            numbers.append(int(f.split(".")[0]))
        except ValueError:
            continue
    return (max(numbers) + 1) if numbers else 1

def log_line(text: str):
    today = datetime.date.today().strftime("%Y_%m_%d")
    log_file = os.path.join(LOGS_DIR, f"log_{today}.txt")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(text + "\n")

def ai_decide_priority(content, why):
    """
    AI automatycznie decyduje jaki priorytet przypisać pamięci
    Na podstawie treści i powodu
    """
    # Prosta heurystyka (możesz to później rozbudować z LLM)
    high_priority_keywords = ["ważne", "pilne", "krytyczne", "musisz", "deadline"]
    medium_keywords = ["może", "warto", "ciekawe", "sprawdzić"]
    
    text = (content + " " + why).lower()
    
    if any(kw in text for kw in high_priority_keywords):
        return 8
    elif any(kw in text for kw in medium_keywords):
        return 5
    else:
        return 3
def auto_tag(content: str):
    """
    Prosty auto-tagger:
    - patrzy na treść
    - wykrywa ważne słowa
    - zwraca listę tagów
    """
    content_low = content.lower()
    tags = set()

    keywords = {
        "eryk": "eryk",
        "ai": "ai",
        "sztuczna inteligencja": "ai",
        "lokalnej": "local_ai",
        "lokalna": "local_ai",
        "system": "system",
        "maria": "maria",
        "pamięć": "memory",
        "pamięci": "memory",
        "język": "language",
        "logiki": "logic",
        "logika": "logic",
        "fundament": "foundation",
        "projekt": "project",
        "tworzyć": "create",
        "tworzy": "create",
        "start": "start",
        "inicjalizacja": "init",
        "inferred": "inferred",
        "reflect": "reflect",
        "think": "think",
        "associate": "associate",
        "refleksja": "reflect",
        "wniosek": "inferred"
    }

    for word, tag in keywords.items():
        if word in content_low:
            tags.add(tag)

    # przykład prostych meta-tagów
    if "2025" in content_low:
        tags.add("time_2025")

    return list(tags)


def handle_MEM(parts):
    """
    MEM|treść|dlaczego|tag1,tag2|priorytet
    """
    now = datetime.datetime.now()
    mem_num = next_memory_number()
    filename = f"{mem_num:03}.txt"
    file_path = os.path.join(MEMORY_DIR, filename)

    content = parts[1] if len(parts) > 1 else ""
    reason = parts[2] if len(parts) > 2 else ""
    tags_raw = parts[3] if len(parts) > 3 else ""
    pri_raw = parts[4] if len(parts) > 4 else "5"

    # ręczne tagi
    tags = [t.strip() for t in tags_raw.split(",")] if tags_raw else []

    # auto-tagging
    auto_tags = auto_tag(content)
    for t in auto_tags:
        if t not in tags:
            tags.append(t)

    # priorytet
    try:
        priority = int(pri_raw)
    except:
        priority = 5

    # usuwanie duplikatów
    unique_tags = list(dict.fromkeys(tags))

    # zapis pamięci
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(f"czas: {now.strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"treść: \"{content}\"\n")
        f.write(f"dlaczego: \"{reason}\"\n")
        f.write(f"powiązania: {unique_tags}\n")
        f.write(f"priorytet: {priority}\n")

    # zapis powiązań tagów
    map_file = os.path.join(LINKS_DIR, f"{mem_num:03}_map.txt")
    with open(map_file, "w", encoding="utf-8") as f:
        for tag in unique_tags:
            if tag:
                f.write(f"{mem_num:03} -> {tag}\n")

    log_line(f"[{now.strftime('%H:%M')}] Dodano rekord pamięci ({filename}) z komendy MEM")


def handle_STATE(parts):
    """
    STATE|stan|kontekst
    """
    now = datetime.datetime.now()
    state = parts[1] if len(parts) > 1 else "nieokreślony"
    context = parts[2] if len(parts) > 2 else ""

    state_file = os.path.join(STATE_DIR, "current.txt")
    with open(state_file, "w", encoding="utf-8") as f:
        f.write(f"czas: {now.strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"stan: \"{state}\"\n")
        f.write(f"kontekst: \"{context}\"\n")
        f.write("energia: 90\n")
        f.write("uwaga: \"normalna\"\n")

    log_line(f"[{now.strftime('%H:%M')}] Zmieniono stan na '{state}' z komendy STATE")

def handle_GOAL(parts):
    """
    GOAL|nazwa|opis|priorytet
    Zapisuje cel systemu.
    """
    now = datetime.datetime.now()
    name = parts[1] if len(parts) > 1 else "bez_nazwy"
    desc = parts[2] if len(parts) > 2 else ""
    pri_raw = parts[3] if len(parts) > 3 else "5"

    try:
        priority = int(pri_raw)
    except:
        priority = 5

    # plik z celem
    safe_name = "".join(c for c in name if c.isalnum() or c in "_-").strip()
    if not safe_name:
        safe_name = "goal"

    filename = f"{now.strftime('%Y%m%d_%H%M%S')}_{safe_name}.txt"
    path = os.path.join(GOALS_DIR, filename)

    with open(path, "w", encoding="utf-8") as f:
        f.write(f"czas: {now.strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"nazwa: \"{name}\"\n")
        f.write(f"opis: \"{desc}\"\n")
        f.write(f"priorytet: {priority}\n")
        f.write(f"status: \"aktywny\"\n")

    log_line(f"[{now.strftime('%H:%M')}] GOAL: dodano cel '{name}' (priorytet={priority})")
    print(f"[GOAL] Zapisano cel '{name}'")
def handle_EVAL_GOAL(parts):
    """
    EVAL_GOAL|nazwa|status|komentarz
    status: 'zrealizowany', 'w_toku', 'porzucony'
    """
    now = datetime.datetime.now()
    name = parts[1] if len(parts) > 1 else ""
    status = parts[2] if len(parts) > 2 else "w_toku"
    comment = parts[3] if len(parts) > 3 else ""

    if not name:
        print("[ERROR] EVAL_GOAL: brak nazwy celu")
        return

    # znajdz ostatni plik z tym celem
    files = sorted(
        [f for f in os.listdir(GOALS_DIR) if name in f],
        reverse=True
    )
    if not files:
        print(f"[ERROR] EVAL_GOAL: nie znaleziono celu '{name}'")
        return

    path = os.path.join(GOALS_DIR, files[0])

    # dopisz ocenę
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\nocena_czas: {now.strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"ocena_status: \"{status}\"\n")
        f.write(f"ocena_komentarz: \"{comment}\"\n")

    log_line(f"[{now.strftime('%H:%M')}] EVAL_GOAL: cel '{name}' -> {status} ({comment})")
    print(f"[OK] EVAL_GOAL: zaktualizowano cel '{name}' -> {status}")


def handle_LINK(parts):
    """
    LINK|numer_pamięci|tag
    """
    now = datetime.datetime.now()
    if len(parts) < 3:
        return
    mem_num = parts[1].strip()
    tag = parts[2].strip()

    # dopisz do odpowiedniej mapy
    map_file = os.path.join(LINKS_DIR, f"{mem_num}_map.txt")
    with open(map_file, "a", encoding="utf-8") as f:
        f.write(f"{mem_num} -> {tag}\n")

    log_line(f"[{now.strftime('%H:%M')}] Dodano powiązanie LINK {mem_num} -> {tag}")

def handle_DEFINE(parts):
    """
    DEFINE|NAZWA|opis|składnia
    """
    if len(parts) < 4:
        return
    name = parts[1].strip()
    desc = parts[2].strip()
    syntax = parts[3].strip()

    spec_file = os.path.join(BASE_DIR, "language_spec.txt")
    with open(spec_file, "a", encoding="utf-8") as f:
        f.write(f"{name} | {desc} | {syntax}\n")

    now = datetime.datetime.now()
    log_line(f"[{now.strftime('%H:%M')}] Zarejestrowano nową komendę języka: {name}")

def handle_REFLECT(parts):
    """
    REFLECT|N|opis

    N - ile ostatnich pamięci wziąć pod uwagę
    opis - dlaczego robimy refleksję / kontekst
    """
    if len(parts) < 2:
        print("❗ REFLECT wymaga co najmniej: REFLECT|N")
        return

    try:
        count = int(parts[1].strip())
    except ValueError:
        print("❗ REFLECT: N musi być liczbą całkowitą.")
        return

    description = parts[2].strip() if len(parts) > 2 else "Refleksja automatyczna systemu"

    # zbierz wszystkie pliki pamięci
    files = [f for f in os.listdir(MEMORY_DIR) if f.endswith(".txt")]
    if not files:
        print("❗ REFLECT: brak pamięci do analizy.")
        return

    # posortuj po numerze malejąco (od najnowszych)
    numbered = []
    for f in files:
        try:
            num = int(f.split(".")[0])
            numbered.append((num, f))
        except ValueError:
            continue

    if not numbered:
        print("❗ REFLECT: brak poprawnie ponumerowanych plików.")
        return

    numbered.sort(reverse=True)  # od największego numeru
    selected = numbered[:count]  # weź N ostatnich

    import re
    collected_texts = []

    for num, fname in selected:
        fpath = os.path.join(MEMORY_DIR, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        collected_texts.append(content)

    if not collected_texts:
        print("❗ REFLECT: nie udało się odczytać żadnych pamięci.")
        return

    # prosta analiza - najczęstsze słowa
    words = re.findall(r"\w+", " ".join(collected_texts).lower())
    freq = {}
    for w in words:
        if len(w) < 4:  # ignoruj bardzo krótkie słowa
            continue
        freq[w] = freq.get(w, 0) + 1

    if freq:
        common = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:7]
        summary = ", ".join([w for w, c in common])
    else:
        summary = "brak wyraźnych motywów"

    # tworzymy nową pamięć jako wynik refleksji
    now = datetime.datetime.now()
    mem_num = next_memory_number()
    filename = f"{mem_num:03}.txt"
    file_path = os.path.join(MEMORY_DIR, filename)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(f"czas: {now.strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"treść: \"Refleksja z ostatnich {len(selected)} pamięci: kluczowe elementy: {summary}\"\n")
        f.write(f"dlaczego: \"{description}\"\n")
        f.write("powiązania: ['INFERRED','REFLECT','AUTO']\n")
        f.write("priorytet: 5\n")

    # mapa powiązań
    map_file = os.path.join(LINKS_DIR, f"{mem_num:03}_map.txt")
    with open(map_file, "w", encoding="utf-8") as f:
        f.write(f"{mem_num:03} -> INFERRED\n")
        f.write(f"{mem_num:03} -> REFLECT\n")
        f.write(f"{mem_num:03} -> AUTO\n")

    log_line(f"[{now.strftime('%H:%M')}] REFLECT wygenerował nowa pamiec ({filename}) z {len(selected)} rekordow")
    print(f"\n[OK] REFLECT utworzyl nowa pamiec: {filename}")


def handle_QUERY(parts):
    """
    QUERY|filter|value|limit(optional)

    Obsługiwane filtry:
      - tag
      - text
      - priority_gt
      - priority_lt
    """
    
    if len(parts) < 3:
        print("❗ QUERY wymaga przynajmniej 3 elementów.")
        return

    filter_type = parts[1].strip()
    value = parts[2].strip()
    limit = int(parts[3]) if len(parts) > 3 else None

    results = []

    for fname in os.listdir(MEMORY_DIR):
        if not fname.endswith(".txt"):
            continue

        fpath = os.path.join(MEMORY_DIR, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()

        # --- filtrowanie ---
        match = False

        if filter_type == "tag":
            if value in content:
                match = True

        elif filter_type == "text":
            if value.lower() in content.lower():
                match = True

        elif filter_type == "priority_gt":
            for line in content.splitlines():
                if line.startswith("priorytet:"):
                    pr = int(line.split(":")[1].strip())
                    if pr > int(value):
                        match = True

        elif filter_type == "priority_lt":
            for line in content.splitlines():
                if line.startswith("priorytet:"):
                    pr = int(line.split(":")[1].strip())
                    if pr < int(value):
                        match = True

        if match:
            results.append(fname)
            if limit and len(results) >= limit:
                break

    # wynik
    print("\n=== WYNIKI QUERY ===")
    if not results:
        print("Brak wyników.")
    else:
        for r in results:
            print(" -", r)

    now = datetime.datetime.now()
    log_line(f"[{now.strftime('%H:%M')}] QUERY({filter_type},{value}) -> {len(results)} wyników")

def handle_THINK(parts):
    """
    THINK|001,002,003|opis
    """
    if len(parts) < 3:
        print("❗ THINK wymaga: THINK|lista|opis")
        return

    mem_list_raw = parts[1]
    description = parts[2]

    mem_ids = [m.strip() for m in mem_list_raw.split(",")]

    collected_texts = []
    collected_reasons = []

    for mem_id in mem_ids:
        fname = f"{mem_id}.txt"
        fpath = os.path.join(MEMORY_DIR, fname)
        if not os.path.isfile(fpath):
            continue

        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()

        collected_texts.append(content)

    if not collected_texts:
        print("❗ THINK: nie znaleziono żadnych pamięci.")
        return

    # proste wydobycie najczęstszych słów
    import re
    words = re.findall(r"\w+", " ".join(collected_texts).lower())
    freq = {}
    for w in words:
        if len(w) < 4:  # ignoruj krótkie słowa
            continue
        freq[w] = freq.get(w, 0) + 1

    if freq:
        common = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:5]
        summary = ", ".join([w for w, c in common])
    else:
        summary = "brak wspólnych elementów"

    # tworzymy nową pamięć
    now = datetime.datetime.now()
    mem_num = next_memory_number()
    filename = f"{mem_num:03}.txt"
    file_path = os.path.join(MEMORY_DIR, filename)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(f"czas: {now.strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"treść: \"Wniosek THINK: wspólne elementy: {summary}\"\n")
        f.write(f"dlaczego: \"{description}\"\n")
        f.write(f"powiązania: ['INFERRED','THINK']\n")
        f.write("priorytet: 4\n")
    # zapis mapy
    map_file = os.path.join(LINKS_DIR, f"{mem_num:03}_map.txt")
    with open(map_file, "w", encoding="utf-8") as f:
        f.write(f"{mem_num:03} -> INFERRED\n")
        f.write(f"{mem_num:03} -> THINK\n")

    # --- SEMANTIC TEST INSIDE THINK ---
    try:
        remember_fact("Agent", "did_think_cycle", "True")
        related = query_related("Agent", "did_think_cycle", depth=1)
        labels = [getattr(n, "label", n.id) for n in related]
        log_line(f"[SEMANTIC TEST] THINK used semantic memory, related: {labels}")
    except Exception as e:
        log_line(f"[SEMANTIC ERROR] {e}")

    log_line(f"[{now.strftime('%H:%M')}] THINK wygenerował nową pamięć ({filename})")

  
def handle_ASSOCIATE(parts):
    """
    ASSOCIATE|
    ASSOCIATE v2 — łączy pamięci TYLKO na podstawie TAGÓW
    (semantycznych powiązań).
    """
    now = datetime.datetime.now()
    associations = []

    # 1. Pobierz wszystkie pamięci
    mem_files = sorted(
        [f for f in os.listdir(MEMORY_DIR) if f.endswith(".txt")]
    )

    memory_entries = {}
    for fmem in mem_files:
        path = os.path.join(MEMORY_DIR, fmem)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()

        # wyciągnij linijkę z tagami
        for line in text.splitlines():
            if line.startswith("powiązania"):
                try:
                    tag_list = eval(line.split(":",1)[1].strip())
                except:
                    tag_list = []
                memory_entries[fmem] = tag_list
                break

    # 2. Porównaj każdy z każdym — ale tylko po TAGACH
    for i, m1 in enumerate(memory_entries):
        tags1 = set(memory_entries[m1])

        for j, m2 in enumerate(memory_entries):
            if j <= i:
                continue

            tags2 = set(memory_entries[m2])
            wspolne = list(tags1.intersection(tags2))

            if wspolne:
                associations.append((m1, m2, wspolne))
                # log relacji
                log_line(f"[{now.strftime('%H:%M')}] ASSOCIATE_v2: {m1} ↔ {m2} wspólne-tag: {wspolne}")

    # 3. Tworzymy metapamięć
    if associations:
        mem_num = next_memory_number()
        fname = f"{mem_num:03}.txt"
        file_path = os.path.join(MEMORY_DIR, fname)

        details = "; ".join([f"{a}-{b}:{','.join(c)}" for (a,b,c) in associations])

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"czas: {now.strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"treść: \"ASSOCIATE_v2 complete\"\n")
            f.write(f"dlaczego: \"mapowanie powiązań semantycznych po tagach\"\n")
            f.write(f"powiązania: ['associate_v2','semantic','relations']\n")
            f.write("priorytet: 6\n")

    print(f"[LINK] ASSOCIATE_v2: utworzono {len(associations)} powiazan.")




def run_script(script_path):
    ensure_dirs()
    if not os.path.isfile(script_path):
        print(f"Nie znaleziono pliku skryptu: {script_path}")
        return

    print(f"[RUN] Uruchamiam skrypt: {script_path}\n")
    with open(script_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split("|")
            cmd = parts[0].strip().upper()

            if cmd == "MEM":
                handle_MEM(parts)
            elif cmd == "STATE":
                handle_STATE(parts)
            elif cmd == "LINK":
                handle_LINK(parts)
            elif cmd == "DEFINE":
                handle_DEFINE(parts)
            elif cmd == "QUERY":
                handle_QUERY(parts)
            elif cmd == "THINK":
                handle_THINK(parts)
            elif cmd == "REFLECT":
                handle_REFLECT(parts)
            elif cmd == "ASSOCIATE":
                handle_ASSOCIATE(parts)
            elif cmd == "GOAL":
                handle_GOAL(parts)
            elif cmd == "EVAL_GOAL":
                handle_EVAL_GOAL(parts)
       
            else:
                print(f"[?] Nieznana komenda: {line}")


    print("\n[OK] Zakonczono wykonywanie skryptu.")
    print(f"Sprawdź foldery 'memory', 'links', 'state' i 'logs' w:\n{BASE_DIR}")
from maria_core.memory_engine.semantic.semantic_bridge import remember_fact, query_related

if __name__ == "__main__":
    if len(sys.argv) < 2:
        script_name = input("Podaj nazwę pliku skryptu (np. script_001.txt): ").strip()
    else:
        script_name = sys.argv[1]
    script_path = os.path.join(BASE_DIR, script_name)
    run_script(script_path)
