#!/usr/bin/env python3
"""Generate a comprehensive PDF summary of the M.A.R.I.A. project."""

import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fpdf import FPDF

# ── Fonts ─────────────────────────────────────────────
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_MONO_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"


class MariaPDF(FPDF):
    """Custom PDF class for M.A.R.I.A. project summary."""

    def __init__(self):
        super().__init__()
        self.add_font("DejaVu", "", FONT_REGULAR)
        self.add_font("DejaVu", "B", FONT_BOLD)
        self.add_font("Mono", "", FONT_MONO)
        self.add_font("Mono", "B", FONT_MONO_BOLD)
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        if self.page_no() > 1:
            self.set_font("DejaVu", "", 7)
            self.set_text_color(120, 120, 120)
            self.cell(0, 5, "M.A.R.I.A. - Project Summary", align="L")
            self.cell(0, 5, f"Strona {self.page_no()}", align="R", new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(200, 200, 200)
            self.line(10, 12, 200, 12)
            self.ln(3)

    def footer(self):
        self.set_y(-15)
        self.set_font("DejaVu", "", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Wygenerowano: {datetime.now().strftime('%Y-%m-%d %H:%M')}", align="C")

    # ── Helpers ───────────────────────────────────────

    def section_title(self, title, size=14):
        self.ln(4)
        self.set_font("DejaVu", "B", size)
        self.set_text_color(30, 60, 120)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(30, 60, 120)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(3)
        self.set_text_color(0, 0, 0)

    def subsection(self, title, size=11):
        self.ln(2)
        self.set_font("DejaVu", "B", size)
        self.set_text_color(60, 90, 140)
        self.cell(0, 6, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)
        self.set_text_color(0, 0, 0)

    def body_text(self, text, size=9):
        self.set_font("DejaVu", "", size)
        self.multi_cell(0, 5, text)
        self.ln(1)

    def mono_text(self, text, size=8):
        self.set_font("Mono", "", size)
        self.set_fill_color(240, 240, 245)
        # Split into lines and render each
        for line in text.split("\n"):
            self.cell(0, 4.5, "  " + line, fill=True, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def bullet(self, text, indent=15, size=9):
        self.set_font("DejaVu", "", size)
        x = self.get_x()
        self.set_x(indent)
        self.cell(4, 5, "\u2022")
        self.multi_cell(0, 5, text)

    def table_row(self, cols, widths, bold=False, fill=False):
        style = "B" if bold else ""
        self.set_font("DejaVu", style, 8)
        if fill:
            self.set_fill_color(230, 235, 245)
        h = 5.5
        for i, (col, w) in enumerate(zip(cols, widths)):
            self.cell(w, h, col, border=1, fill=fill)
        self.ln(h)

    def kv_line(self, key, value, key_w=45):
        self.set_font("DejaVu", "B", 9)
        self.cell(key_w, 5, key)
        self.set_font("DejaVu", "", 9)
        self.cell(0, 5, str(value), new_x="LMARGIN", new_y="NEXT")


def build_pdf():
    pdf = MariaPDF()

    # ══════════════════════════════════════════════════
    # STRONA TYTULOWA
    # ══════════════════════════════════════════════════
    pdf.add_page()
    pdf.ln(30)

    # Logo / Title
    pdf.set_font("DejaVu", "B", 28)
    pdf.set_text_color(30, 60, 120)
    pdf.cell(0, 15, "M.A.R.I.A.", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("DejaVu", "", 11)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 7, "Meta Analysis Recalibration Intelligence Architecture",
             align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    pdf.set_draw_color(30, 60, 120)
    pdf.line(60, pdf.get_y(), 150, pdf.get_y())
    pdf.ln(8)

    pdf.set_font("DejaVu", "B", 14)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(0, 8, "Podsumowanie projektu", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    pdf.set_font("DejaVu", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"Data: {datetime.now().strftime('%d.%m.%Y')}",
             align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, "Wersja: 4.0 | Branch: refactor/homeostasis",
             align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, "Hardware: NiPoGi Mini PC (AMD Ryzen 5, 32GB RAM, Ubuntu 22.04)",
             align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(15)

    # Key numbers box
    pdf.set_fill_color(240, 243, 250)
    pdf.set_draw_color(30, 60, 120)
    box_y = pdf.get_y()
    pdf.rect(30, box_y, 150, 40, style="DF")

    pdf.set_y(box_y + 4)
    pdf.set_font("DejaVu", "B", 10)
    pdf.set_text_color(30, 60, 120)
    pdf.cell(0, 6, "KLUCZOWE METRYKI", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    metrics = [
        ("156 plikow Python", "35 493 linii kodu", "668 testow"),
        ("27 modulow", "25+ komend REPL", "20 plikow dokumentacji"),
        ("32 commitow", "Wdrozony produkcyjnie", "Od 14.11.2025"),
    ]
    pdf.set_font("DejaVu", "", 9)
    pdf.set_text_color(50, 50, 50)
    for row in metrics:
        for item in row:
            pdf.cell(63.3, 5, item, align="C")
        pdf.ln(5)

    pdf.ln(15)
    pdf.set_font("DejaVu", "", 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 5, "M.A.R.I.A. Project | AGPL-3.0",
             align="C", new_x="LMARGIN", new_y="NEXT")

    # ══════════════════════════════════════════════════
    # 1. CZYM JEST M.A.R.I.A.
    # ══════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("1. Czym jest M.A.R.I.A.?")

    pdf.body_text(
        "M.A.R.I.A. (Meta Analysis Recalibration Intelligence Architecture) to lokalny, "
        "autonomiczny agent AI zaprojektowany do samodzielnego uczenia sie z plikow tekstowych. "
        "Dziala offline-first na dedykowanym mini PC, korzystajac z modeli LLM uruchamianych "
        "lokalnie przez Ollama oraz zdalnie przez NVIDIA NIM API."
    )

    pdf.body_text(
        "Projekt rozpoczal sie 14 listopada 2025 i od tego czasu przeszedl przez cztery wersje, "
        "rozrastajac sie z prostego skryptu do zlozonego systemu z homeostaza, swiadomoscia, "
        "autonomicznym uczeniem sie i interfejsem webowym."
    )

    pdf.subsection("Glowne cechy")
    features = [
        "Samodzielne uczenie sie z plikow .txt (chunking, ekstrakcja wiedzy, egzaminy)",
        "Homeostaza - autonomiczna regulacja trybow pracy (ACTIVE/REDUCED/SLEEP/SURVIVAL)",
        "Swiadomosc - 7 cech osobowosci (rozszerzalne), pamiec rozmow, sny, ciaglosc tozsamosci",
        "Agent Nauczyciel - autonomicznie decyduje co i kiedy sie uczyc",
        "Pamiec semantyczna - graf wiedzy z cosine similarity i konsolidacja",
        "REPL + Web UI - interakcja przez terminal lub przegladarke",
        "Introspekcja kodu - Maria analizuje swoja wlasna architekture (READ-ONLY)",
        "Hybrid LLM routing - Ollama (chat) + NIM (nauka) z auto-fallback",
    ]
    for f in features:
        pdf.bullet(f)

    pdf.subsection("Stack technologiczny")
    pdf.kv_line("Jezyk:", "Python 3.10")
    pdf.kv_line("LLM lokalny:", "Ollama (llama3.1:8b, 4.9GB)")
    pdf.kv_line("LLM zdalny:", "NVIDIA NIM API (z-ai/glm5)")
    pdf.kv_line("Hardware:", "NiPoGi Mini PC, AMD Ryzen 5 7430U, 32GB RAM, 1TB SSD")
    pdf.kv_line("OS:", "Ubuntu 22.04 LTS")
    pdf.kv_line("Web UI:", "Flask + Flask-SocketIO + WebSocket")
    pdf.kv_line("Dane:", "JSONL (source of truth) + graf semantyczny (cache)")
    pdf.kv_line("Testy:", "pytest (668 passing)")

    # ══════════════════════════════════════════════════
    # 2. HISTORIA PROJEKTU
    # ══════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("2. Historia projektu")

    timeline = [
        ("2025-11-14", "Poczatek projektu M.A.R.I.A."),
        ("2025-11 \u2192 2026-01", "Rozwoj z 4 roznymi LLM, reczne sklejanie kodu"),
        ("2026-01", "Homeostasis - pierwszy modul z pomoca Claude"),
        ("2026-02-01", "Specyfikacje: Code Agent, Web UI, Consciousness"),
        ("2026-02-01", "Introspection module + Vision spec + Folder cleanup"),
        ("2026-02-01", "Web UI complete (Flask + WebSocket + chat + PIN auth)"),
        ("2026-02-02", "TimeAwareness + Smart Home spec"),
        ("2026-02-22", "Linux migration prep + DEPLOY na Mini PC"),
        ("2026-02-23", "SSH hardening + WireGuard VPN + NVIDIA NIM API"),
        ("2026-02-25", "Self-Awareness (ContextBuilder) + /awareness REPL"),
        ("2026-02-27", "Consciousness Phase C: personality, dreams, conversation memory"),
        ("2026-02-27", "Agent Nauczyciel + autonomiczny trigger w homeostasis"),
    ]

    widths = [35, 145]
    pdf.table_row(["Data", "Wydarzenie"], widths, bold=True, fill=True)
    for i, (date, event) in enumerate(timeline):
        pdf.table_row([date, event], widths, fill=(i % 2 == 0))

    # ══════════════════════════════════════════════════
    # 3. ARCHITEKTURA
    # ══════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("3. Architektura systemu")

    pdf.subsection("Warstwy architektury")
    pdf.mono_text(
        "+-----------------------------------------------------------+\n"
        "|  WARSTWA WEJSCIA                                          |\n"
        "|  main.py (REPL)  |  run_maria.py (daemon)  |  Web UI     |\n"
        "+-----------------------------------------------------------+\n"
        "                         |\n"
        "                         v\n"
        "+-----------------------------------------------------------+\n"
        "|  WARSTWA STEROWANIA                                       |\n"
        "|  HomeostasisCore  |  ModeRegulator  |  ResourceWatchdog   |\n"
        "+-----------------------------------------------------------+\n"
        "                         |\n"
        "                         v\n"
        "+-----------------------------------------------------------+\n"
        "|  WARSTWA PERCEPCJI + UCZENIA                              |\n"
        "|  Perception  |  LearningAgent  |  ExamAgent  |  Teacher  |\n"
        "+-----------------------------------------------------------+\n"
        "                         |\n"
        "                         v\n"
        "+-----------------------------------------------------------+\n"
        "|  WARSTWA PAMIECI                                          |\n"
        "|  MemoryStore (JSONL)  |  SemanticGraph  |  EpisodicMem   |\n"
        "+-----------------------------------------------------------+\n"
        "                         |\n"
        "                         v\n"
        "+-----------------------------------------------------------+\n"
        "|  WARSTWA SWIADOMOSCI                                      |\n"
        "|  SelfModel  |  IdentityStore  |  TraitEvolver  |  Dreams |\n"
        "+-----------------------------------------------------------+"
    )

    pdf.subsection("Tryby pracy (Mode Regulator)")
    pdf.body_text(
        "System homeostazy automatycznie przelacza miedzy trybami na podstawie "
        "dostepnych zasobow (RAM, CPU, disk) i stanu systemu:"
    )
    modes = [
        ("ACTIVE", "Pelna operacja - uczenie, rozmowy, analiza"),
        ("REDUCED", "Ograniczone zasoby - ostrzezenia, mniejsza aktywnosc"),
        ("SLEEP", "Niski pobor - konsolidacja pamieci, generowanie snow"),
        ("SURVIVAL", "Tryb awaryjny - tylko podstawowe operacje"),
        ("RECOVERY", "Auto-naprawa po awarii"),
    ]
    widths = [30, 150]
    pdf.table_row(["Tryb", "Opis"], widths, bold=True, fill=True)
    for i, (mode, desc) in enumerate(modes):
        pdf.table_row([mode, desc], widths, fill=(i % 2 == 0))

    pdf.subsection("Petla 1Hz Tick (Homeostasis Core)")
    pdf.body_text(
        "Serce systemu - petla wykonywana co sekunde w 9 fazach:"
    )
    phases = [
        ("Phase 1", "SENSE", "Odczyt sensorow (RAM, CPU, disk, temperatura)"),
        ("Phase 2", "INTERPRET", "Interpretacja semantyczna stanu"),
        ("Phase 3", "VALIDATE", "Walidacja ograniczen i progrow"),
        ("Phase 4", "DECIDE", "Decyzja o zmianie trybu"),
        ("Phase 5", "GENERATE", "Generowanie akcji korekcyjnych"),
        ("Phase 6", "EXECUTE", "Wykonanie akcji"),
        ("Phase 7", "HEALTH", "Obliczenie health score"),
        ("Phase 8", "AUDIT", "Audyt i logowanie zdarzen"),
        ("Phase 9", "TEACHER", "Sprawdzenie triggera autonomicznej nauki"),
    ]
    widths = [20, 25, 135]
    pdf.table_row(["Faza", "Nazwa", "Opis"], widths, bold=True, fill=True)
    for i, (phase, name, desc) in enumerate(phases):
        pdf.table_row([phase, name, desc], widths, fill=(i % 2 == 0))

    # ══════════════════════════════════════════════════
    # 4. MODULY
    # ══════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("4. Moduly systemu")

    pdf.subsection("agent_core/ (nowy system - 15 modulow)")
    agent_modules = [
        ("adapters", "Wrappery legacy kodu (brain, memory, resource, semantic)"),
        ("awareness", "Swiadomosc czasu i kontekstu (TimeAwareness, ContextBuilder)"),
        ("consciousness", "Osobowosc, tozsamosc, pamiec rozmow, sny, emocje"),
        ("data", "Struktury danych i modele"),
        ("executor", "Wykonywanie modulow i dispatch sygnalow"),
        ("homeostasis", "Rdzen regulacji (sensory, tryby, ograniczenia, event logger)"),
        ("introspection", "Samoanaliza kodu READ-ONLY (AST, raporty, scheduler)"),
        ("llm", "Zarzadzanie LLM (NIM client, budzet tokenow, router, latency)"),
        ("memory", "Ujednolicone zarzadzanie pamiecia (epizodyczna, semantyczna)"),
        ("metacontrol", "Meta-kontroler do zarzadzania systemem"),
        ("modules", "Moduly pluginowe (10 modulow REPL)"),
        ("registry", "Rejestr modulow, dispatcher komend, SharedContext"),
        ("teacher", "Autonomiczny agent nauczyciel (decyzje + sesje nauki)"),
        ("tests", "21 plikow testowych, 668 funkcji testowych"),
        ("ui", "API telemetryczne i interfejs uzytkownika"),
    ]
    widths = [35, 145]
    pdf.table_row(["Modul", "Opis"], widths, bold=True, fill=True)
    for i, (mod, desc) in enumerate(agent_modules):
        pdf.table_row([mod, desc], widths, fill=(i % 2 == 0))

    pdf.ln(3)
    pdf.subsection("maria_core/ (legacy system - 12 modulow)")
    maria_modules = [
        ("agent", "Legacy implementacja agenta"),
        ("brain", "Interfejs Ollama (OllamaBrain)"),
        ("input", "Przetwarzanie plikow wejsciowych"),
        ("learning", "Algorytmy uczenia (chunking, ekstrakcja, egzaminy)"),
        ("logs", "System logowania"),
        ("memory", "Legacy pamiec epizodyczna i semantyczna"),
        ("memory_engine", "Integracja brain-memory (graf semantyczny)"),
        ("meta", "Meta-kontrola i konfiguracja"),
        ("output", "Generowanie odpowiedzi"),
        ("perception", "Skanowanie plikow i percepcja"),
        ("sys", "Konfiguracja systemowa i watchdog"),
        ("utils", "Funkcje pomocnicze"),
    ]
    widths = [35, 145]
    pdf.table_row(["Modul", "Opis"], widths, bold=True, fill=True)
    for i, (mod, desc) in enumerate(maria_modules):
        pdf.table_row([mod, desc], widths, fill=(i % 2 == 0))

    # ══════════════════════════════════════════════════
    # 5. SWIADOMOSC
    # ══════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("5. System swiadomosci")

    pdf.body_text(
        "Modul swiadomosci (agent_core/consciousness/) daje Marii poczucie tozsamosci, "
        "osobowosc i ciaglosc miedzy sesjami. Sklada sie z kilku wspolpracujacych komponentow:"
    )

    pdf.subsection("Osobowosc (TraitEvolver + TraitCatalog)")
    pdf.body_text(
        "7 cech osobowosci (rozszerzalnych) - kazda cecha ma wartosc 0.0-1.0 "
        "i ewoluuje dynamicznie na podstawie interakcji z uzytkownikiem:"
    )
    traits = [
        ("ciekawska", "Chce poznawac nowe rzeczy (sygnaly: perception, learning, unknown terms)"),
        ("systematyczna", "Pracuje metodycznie (sygnaly: exam passed, learning completed)"),
        ("pomocna", "Lubi pomagac i odpowiadac (sygnaly: conversation turns)"),
        ("wytrwala", "Nie poddaje sie przy trudnych tematach (sygnaly: hard topic retry)"),
        ("cierpliwa", "Znosi trudnosci ze spokojem (sygnaly: survival recovery, reduced mode)"),
        ("refleksyjna", "Analizuje swoje doswiadczenia (sygnaly: introspection runs)"),
        ("spoleczna", "Lubi interakcje z operatorem (sygnaly: conversation, greeting)"),
    ]
    widths = [30, 150]
    pdf.table_row(["Cecha", "Opis i sygnaly"], widths, bold=True, fill=True)
    for i, (name, desc) in enumerate(traits):
        pdf.table_row([name, desc], widths, fill=(i % 2 == 0))

    pdf.subsection("Pamiec rozmow (ConversationMemory)")
    pdf.body_text(
        "Rolling context ostatnich N wiadomosci z automatyczna kondensacja przez LLM. "
        "Pozwala Marii pamietac kontekst rozmowy i budowac na nim."
    )

    pdf.subsection("Sny (SleepProcessor + DreamGenerator)")
    pdf.body_text(
        "Gdy Maria przechodzi w tryb SLEEP, uruchamia sie proces konsolidacji pamieci. "
        "DreamGenerator tworzy 'sny' - kreatywne polaczenia miedzy wezlami grafu semantycznego, "
        "ktore moga prowadzic do nowych skojarzen i odkryc."
    )

    pdf.subsection("Ciaglosc tozsamosci (IdentityStore)")
    pdf.body_text(
        "Dane persistentne w meta_data/consciousness_identity.json: data urodzenia, "
        "liczba sesji, calkowity uptime, snapshot osobowosci. Maria wie kim jest "
        "miedzy restartami."
    )

    # ══════════════════════════════════════════════════
    # 6. AGENT NAUCZYCIEL
    # ══════════════════════════════════════════════════
    pdf.section_title("6. Agent Nauczyciel")

    pdf.body_text(
        "Autonomiczny agent decydujacy co, kiedy i jak sie uczyc. Uzywa 6-priorytetowego "
        "silnika decyzyjnego (P1-P6) bez potrzeby interwencji uzytkownika."
    )

    pdf.subsection("Silnik decyzyjny - priorytety")
    priorities = [
        ("P1", "Kontynuuj nauke", "Plik w trakcie uczenia (status: learning)"),
        ("P2", "Egzaminuj", "Plik gotowy do egzaminu (>= 80% chunkow)"),
        ("P3", "Zacznij nowy", "Plik o najwyzszym priorytecie (status: new)"),
        ("P4", "Powtorka", "Spaced repetition - plik wymagajacy powtorki"),
        ("P5", "Trudny temat", "Ponow probe z plikiem oznaczonym hard_topic"),
        ("P6", "Analiza luk", "NIM gap analysis - glebokie wyszukanie brakow"),
    ]
    widths = [12, 35, 133]
    pdf.table_row(["#", "Strategia", "Opis"], widths, bold=True, fill=True)
    for i, (p, name, desc) in enumerate(priorities):
        pdf.table_row([p, name, desc], widths, fill=(i % 2 == 0))

    pdf.subsection("Autonomiczny trigger (Homeostasis Phase 9)")
    pdf.body_text(
        "Agent Nauczyciel jest podlaczony do petli homeostazy. Gdy Maria jest w trybie "
        "ACTIVE i nikt z nia nie rozmawia od 10 minut, automatycznie uruchamia krotka "
        "sesje nauki (3 iteracje). Cooldown miedzy sesjami: 15 minut."
    )
    conditions = [
        "Tryb = ACTIVE",
        "Idle >= 600 sekund (10 minut)",
        "Teacher agent podlaczony (set_teacher_agent)",
        "Brak aktywnej sesji nauki (thread = None)",
        "Cooldown minoal (ostatnia sesja > 900s temu)",
    ]
    for c in conditions:
        pdf.bullet(c)

    # ══════════════════════════════════════════════════
    # 7. KOMENDY REPL
    # ══════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("7. Komendy REPL")

    pdf.body_text(
        "Maria oferuje rozbudowany interfejs terminalowy (REPL) z ponad 25 komendami "
        "pogrupowanymi tematycznie:"
    )

    commands = [
        ("[CORE]", [
            ("/help", "Lista wszystkich komend"),
            ("/exit", "Zamknij sesje"),
            ("/status", "Status systemu (RAM, CPU, uptime)"),
        ]),
        ("[LEARNING]", [
            ("/learn", "Skanuj input/ i ucz sie"),
            ("/learn history [N]", "Historia zdarzen nauki"),
            ("/learn stats", "Statystyki bazy wiedzy"),
            ("/learn file <id>", "Szczegoly pliku"),
        ]),
        ("[TEACHER]", [
            ("/teacher [N]", "Sesja nauki (N iteracji)"),
            ("/teacher status", "Status agenta"),
            ("/teacher plan", "Podglad nastepnego kroku"),
            ("/teacher history [N]", "Historia planow"),
        ]),
        ("[HOMEOSTASIS]", [
            ("/homeostasis", "Status homeostazy"),
            ("/homeostasis start/stop", "Kontrola petli"),
            ("/homeostasis events N", "Ostatnie N zdarzen"),
            ("/homeostasis summary", "Podsumowanie sesji"),
        ]),
        ("[CONSCIOUSNESS]", [
            ("/consciousness", "Status swiadomosci"),
            ("/awareness", "Kontekst samowiedzy"),
        ]),
        ("[INTROSPECTION]", [
            ("/introspect", "Jak jestem zbudowana (human summary)"),
            ("/introspect detail", "Raport techniczny"),
            ("/introspect issues", "TODO/FIXME w kodzie"),
            ("/introspect module X", "Info o module X"),
        ]),
        ("[NIM]", [
            ("/nim status", "Status NIM API i budzet tokenow"),
        ]),
    ]

    for category, cmds in commands:
        pdf.subsection(category)
        widths_cmd = [45, 135]
        for cmd, desc in cmds:
            pdf.set_font("Mono", "", 8)
            pdf.cell(widths_cmd[0], 5, cmd)
            pdf.set_font("DejaVu", "", 8)
            pdf.cell(widths_cmd[1], 5, desc, new_x="LMARGIN", new_y="NEXT")

    # ══════════════════════════════════════════════════
    # 8. INFRASTRUKTURA
    # ══════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("8. Infrastruktura i deploy")

    pdf.subsection("Hardware")
    pdf.kv_line("Maszyna:", "NiPoGi Mini PC")
    pdf.kv_line("CPU:", "AMD Ryzen 5 7430U")
    pdf.kv_line("RAM:", "32 GB")
    pdf.kv_line("Dysk:", "1 TB SSD")
    pdf.kv_line("OS:", "Ubuntu 22.04 LTS")
    pdf.kv_line("IP LAN:", "192.168.1.32")
    pdf.kv_line("Deploy:", "22.02.2026")

    pdf.subsection("Security")
    security = [
        "UFW: deny all incoming, allow SSH + 5000 z LAN (192.168.1.0/24)",
        "fail2ban: sshd jail (5 prob -> ban 1h)",
        "SSH: klucz ed25519, PasswordAuthentication no, MaxAuthTries 3",
        "Automatyczne security updates (unattended-upgrades)",
        "User maria bez sudo (aplikacja), deployadmin z sudo (admin)",
        ".env chmod 600",
        "WireGuard VPN dla zdalnego dostepu",
    ]
    for s in security:
        pdf.bullet(s)

    pdf.subsection("Systemd services")
    pdf.kv_line("maria-ui.service:", "Web UI (Flask) - active, enabled")
    pdf.kv_line("maria.service:", "REPL daemon - enabled")
    pdf.kv_line("Backup:", "Cron codziennie o 3:00 -> /home/maria/maria_backups/")

    pdf.subsection("Web UI")
    pdf.kv_line("URL:", "http://192.168.1.32:5000")
    pdf.kv_line("Auth:", "PIN (4 cyfry)")
    pdf.kv_line("Funkcje:", "Chat, Status dashboard, Powiadomienia toast")
    pdf.kv_line("Rate limit:", "2 wiadomosci / 60s")
    pdf.kv_line("Stack:", "Flask + Flask-SocketIO + WebSocket")

    # ══════════════════════════════════════════════════
    # 9. ROADMAP
    # ══════════════════════════════════════════════════
    pdf.section_title("9. Roadmap rozwoju")

    phases = [
        ("A", "Stabilizacja", "COMPLETE",
         "Naprawienie bledow, stabilny runtime, spojne sciezki."),
        ("B", "Full Homeostasis", "COMPLETE",
         "Pelna autonomia z petlami regulacji, 1Hz tick, tryby pracy."),
        ("C", "Consciousness", "IN PROGRESS",
         "Samowiedza, osobowosc, sny, ciaglosc tozsamosci, teacher."),
        ("D", "Vision", "PLANNED",
         "Percepcja wizualna: kamera USB, detekcja ruchu, rozp. twarzy."),
        ("E", "Smart Home", "PLANNED",
         "IoT (Shelly/Tasmota), automatyzacja, mobilne cialo Android."),
        ("F", "Multi-Source Learning", "PLANNED",
         "Nauka z wielu zrodel z walidacja krzyzowa."),
        ("G", "Multi-Agent", "PLANNED",
         "System mentor-student z wieloma agentami."),
    ]

    widths = [10, 38, 28, 104]
    pdf.table_row(["#", "Nazwa", "Status", "Opis"], widths, bold=True, fill=True)
    for i, (letter, name, status, desc) in enumerate(phases):
        pdf.table_row([letter, name, status, desc], widths, fill=(i % 2 == 0))

    # ══════════════════════════════════════════════════
    # 10. METRYKI KODU
    # ══════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("10. Metryki kodu")

    stats = [
        ("Pliki Python (total)", "156"),
        ("Linie kodu (total)", "35 493"),
        ("Pliki testowe", "21"),
        ("Funkcje testowe", "668"),
        ("% kodu to testy", "~26.5%"),
        ("Moduly agent_core/", "15"),
        ("Moduly maria_core/", "12"),
        ("Komendy REPL", "25+"),
        ("Pliki dokumentacji", "20"),
        ("Commity (branch)", "32"),
        ("Data pierwszego commita", "2025-11-14"),
        ("Data ostatniego commita", "2026-02-27"),
    ]

    widths = [60, 40]
    pdf.table_row(["Metryka", "Wartosc"], widths, bold=True, fill=True)
    for i, (metric, value) in enumerate(stats):
        pdf.table_row([metric, value], widths, fill=(i % 2 == 0))

    pdf.ln(5)
    pdf.subsection("Struktura plikow testowych")
    test_files = [
        ("test_teacher.py", "75", "Agent Nauczyciel + auto-trigger"),
        ("test_homeostasis.py", "~120", "Core homeostasis + tick loop"),
        ("test_personality.py", "~50", "Cechy osobowosci + ewolucja"),
        ("test_sleep.py", "~40", "Sleep processor + dream generator"),
        ("test_conversation_memory.py", "~30", "Pamiec rozmow + kondensacja"),
        ("test_nim_client.py", "58", "NIM API client + token budget"),
        ("test_introspection.py", "27", "Code self-analysis"),
        ("test_time_awareness.py", "25", "Percepcja czasu"),
        ("+ 13 innych", "~243", "API, adaptery, sensory, memory..."),
    ]
    widths = [55, 18, 107]
    pdf.table_row(["Plik", "Testy", "Zakres"], widths, bold=True, fill=True)
    for i, (f, count, scope) in enumerate(test_files):
        pdf.table_row([f, count, scope], widths, fill=(i % 2 == 0))

    # ══════════════════════════════════════════════════
    # 11. DECYZJE ARCHITEKTONICZNE
    # ══════════════════════════════════════════════════
    pdf.ln(3)
    pdf.section_title("11. Decyzje architektoniczne (ADR)")

    adrs = [
        ("ADR-001", "JSONL jako source of truth, graf jako derived cache"),
        ("ADR-002", "Threading (nie asyncio) - zgodnosc ze specyfikacja"),
        ("ADR-003", "agent_core/ w root projektu (nie w maria_core/)"),
        ("ADR-004", "Code Agent jako osobne urzadzenie z wymienialnym LLM"),
        ("ADR-005", "Brak emoji w kodzie produkcyjnym (kompatybilnosc terminali)"),
        ("ADR-006", "Introspection tylko READ-ONLY (Maria nie modyfikuje kodu)"),
        ("ADR-007", "Smart Home - tylko lokalne API (Shelly/Tasmota), bez chmury"),
        ("ADR-008", "NIM do nauki, Ollama do chatu (hybrid routing z auto-fallback)"),
    ]
    widths = [22, 158]
    pdf.table_row(["ADR", "Decyzja"], widths, bold=True, fill=True)
    for i, (adr, decision) in enumerate(adrs):
        pdf.table_row([adr, decision], widths, fill=(i % 2 == 0))

    # ══════════════════════════════════════════════════
    # 12. STRUKTURA KATALOGOW
    # ══════════════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("12. Struktura projektu")

    pdf.mono_text(
        "maria/\n"
        "|\n"
        "|-- main.py                  # REPL interface (Ver.1.2)\n"
        "|-- run_maria.py             # Daemon mode (learning loop)\n"
        "|-- run_ui.py                # Web UI launcher\n"
        "|-- .env                     # Konfiguracja (PIN, NIM key, CORS)\n"
        "|\n"
        "|-- agent_core/              # NOWY system (15 modulow)\n"
        "|   |-- homeostasis/         # Rdzen: sensory, tryby, 1Hz tick\n"
        "|   |-- consciousness/       # Osobowosc, sny, tozsamosc\n"
        "|   |-- teacher/             # Agent Nauczyciel\n"
        "|   |-- introspection/       # Samoanaliza kodu (READ-ONLY)\n"
        "|   |-- llm/                 # NIM client, router, token budget\n"
        "|   |-- memory/              # Ujednolicona pamiec\n"
        "|   |-- awareness/           # TimeAwareness, ContextBuilder\n"
        "|   |-- modules/             # 10 modulow REPL (pluginy)\n"
        "|   |-- registry/            # Rejestr modulow + SharedContext\n"
        "|   |-- adapters/            # Wrappery legacy kodu\n"
        "|   |-- tests/               # 21 plikow, 668 testow\n"
        "|   +-- ...\n"
        "|\n"
        "|-- maria_core/              # Legacy system (12 modulow)\n"
        "|   |-- brain/               # ollama_brain.py\n"
        "|   |-- learning/            # learning_agent.py, exam_agent.py\n"
        "|   |-- memory/              # memory_store.py, semantic_graph.py\n"
        "|   |-- perception/          # perception.py\n"
        "|   +-- ...\n"
        "|\n"
        "|-- maria_ui/                # Web UI (Flask + SocketIO)\n"
        "|   |-- app.py               # Server + chat + notifications\n"
        "|   |-- templates/           # login.html, index.html, status.html\n"
        "|   +-- config.py            # PIN, rate limits\n"
        "|\n"
        "|-- models/                  # LLM interface\n"
        "|   +-- ollama_brain.py      # OllamaBrain + personality inject\n"
        "|\n"
        "|-- docs/                    # 20 plikow dokumentacji\n"
        "|-- scripts/                 # systemd, backup, install\n"
        "|-- meta_data/               # Runtime data (identity, events)\n"
        "|-- input/                   # Pliki .txt do nauki\n"
        "+-- claude_notes/            # Notatki Claude miedzy sesjami"
    )

    # ══════════════════════════════════════════════════
    # LAST PAGE
    # ══════════════════════════════════════════════════
    pdf.add_page()
    pdf.ln(40)

    pdf.set_font("DejaVu", "B", 18)
    pdf.set_text_color(30, 60, 120)
    pdf.cell(0, 10, "M.A.R.I.A.", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("DejaVu", "", 10)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 6, "Meta Analysis Recalibration Intelligence Architecture",
             align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    pdf.set_draw_color(30, 60, 120)
    pdf.line(70, pdf.get_y(), 140, pdf.get_y())
    pdf.ln(8)

    pdf.set_font("DejaVu", "", 9)
    pdf.set_text_color(100, 100, 100)
    lines = [
        "Projekt zapoczatkowany: 14 listopada 2025",
        "Wdrozony produkcyjnie: 22 lutego 2026",
        "",
        "156 plikow | 35 493 linii kodu | 668 testow",
        "",
        f"Podsumowanie wygenerowane: {datetime.now().strftime('%d.%m.%Y')}",
    ]
    for line in lines:
        pdf.cell(0, 6, line, align="C", new_x="LMARGIN", new_y="NEXT")

    # ── Save ──────────────────────────────────────────
    output_path = PROJECT_ROOT / "MARIA_Project_Summary.pdf"
    pdf.output(str(output_path))
    print(f"PDF saved: {output_path}")
    print(f"Pages: {pdf.page_no()}")
    return output_path


if __name__ == "__main__":
    build_pdf()
