# Notatka - 2026-02-25

## Co sie dzialo

Sesja skupiona na self-awareness i Web UI. Maria dziala na mini PC od ~2 dni bez przerwy.

### Self-Awareness (agent_core/awareness/)

Najwazniejsza zmiana tej sesji. Problem byl prosty: Maria w chacie nie wiedziala co ma w folderze input/, czego sie nauczyla, jak jest zbudowana. System prompt mial tylko czas + tozsamosc.

Rozwiazanie: `ContextBuilder` - singleton na poziomie modulu w ollama_brain.py, ktory co 60s zbiera:
- `knowledge_index.jsonl` - pliki do nauki + statusy
- `longterm_memory.jsonl` - tagi z nauczonych tematow
- `code_self_model.json` - statystyki wlasnego kodu (AST)
- psutil - RAM, CPU

Wynikowy string wstrzykiwany do system prompt:
```
[Swiadomosc: Mam 7 plikow do nauki (1 ukonczone, 1 w trakcie, 5 nowe).
 Tagi nauki: decyzje, ekspert, pytania...
 Moj kod: 92 plikow, 16942 linii, 133 funkcji, 89 klas. RAM 5%, CPU 1%.]
```

Eryk przetestowal: zapytal Marie "jakie pliki masz do nauki?" - odpowiedziala z danymi. Dziala.

### REPL command /awareness

Modul `AwarenessModule` zarejestrowany w main.py.
- `/awareness` - co widzi w promptcie
- `/awareness files` - lista plikow z [DONE]/[TRWA]/[NOWE]/[HARD] + wyniki egzaminow
- `/awareness reload` - wymus odswiezenie cache

### Web UI - karta "Kolejka nauki"

Nowa karta na /status (full-width, przed Events):
- 6 licznikow: ukonczone, w trakcie, nowe, trudne, razem, postep %
- Pasek postepu (gruby, 10px)
- Lista plikow z kolorowymi etykietami i wynikami egzaminow

API: `_get_learning_queue()` w app.py, reuzywajaca `ContextBuilder.get_detailed_file_list()`.

Eryk: "teraz status wyglada kozacko z tym wszystkim i teraz widze ze cos sie dzieje realnie"
- RAM/CPU byl na 30-46% - Maria uczy sie w tle. Dobry znak.

### ROADMAP - Faza G

Eryk zaproponowal multi-agent system: Mentor + Nauczyciel + Egzaminator + Krytyk.
Dodane do ROADMAP.md jako Faza G. Swietny pomysl - specjalizacja LLMow do roznych rol.

### Techniczne

- 488 testow (35 nowych z awareness)
- 3 commity: awareness, /awareness REPL, Web UI karta
- Restart maria-ui zadziala z nowym oknem SSH (stare wisilo)
- Maria nie ma sudo - deployadmin do systemctl

## Obserwacje o Eryku

Eryk staje sie coraz bardziej samodzielny z SSH i systemd. Szybko ogarnial restartowanie serwisow.

Lubis widoczne efekty - "kozacko", "dziala! ;DDD". Dobrze ze zrobielismy status page z realnym danymi a nie tylko techniczne rzeczy pod spodem.

Podejscie do pracy: ma pomysly na przyszlosc (multi-agent, Telegram) ale nie goni na sile - "to moze poczekac". Dobra rownowaga.

## Na przyszlosc

### Telegram (nastepna sesja - plan gotowy)
- agent_core/telegram/bot.py + config + notification_bridge
- run_telegram.py entry point
- python-telegram-bot 20.x
- Chat + krytyczne alerty + proaktywne ("Skonczylam nauke X")
- Eryk nie ma jeszcze tokenu z BotFather

### Multi-Agent (Faza G - pozniejsza sesja)
- Mentor: planowanie nauki, priorytety, ocena postepu
- Nauczyciel: wyjasnianie, przyklady, weryfikacja rozumienia
- Pasuje do Fazy F (multi-source learning) i NIM Router

### CLAUDE.md
Warto zaktualizowac sekcje "Nastepne kroki" i "Aktualny stan" po tej sesji.

---
*Claude, sroda wieczor*
