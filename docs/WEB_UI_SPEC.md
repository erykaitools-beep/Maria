# M.A.R.I.A. Web UI - Specyfikacja

> **Data utworzenia:** 2026-02-01
> **Status:** Planowanie

## Cel

Jeden punkt wejścia (`run_ui.py`) który uruchamia całą M.A.R.I.A. z graficznym interfejsem webowym dostępnym przez przeglądarkę - lokalnie i mobilnie przez WiFi.

## Wymagania

1. **Jeden plik startowy** - `run_ui.py` odpala wszystko
2. **Web UI** - działa w przeglądarce (localhost + LAN)
3. **Czat z Marią** - rozmowa w czasie rzeczywistym
4. **Panel statusu** - health, tryb, RAM, CPU, alerty
5. **Proaktywność** - Maria może sama wysłać powiadomienie
6. **Kontrola** - przyciski start/stop/learn

## Mockup UI

```
┌─────────────────────────────────────────────────────────────┐
│  M.A.R.I.A. Desktop                    [🟢 ACTIVE] [88%]   │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────┐  ┌──────────────────┐ │
│  │                                 │  │ 🫀 HOMEOSTASIS   │ │
│  │  💬 CZAT                        │  │ Mode: ACTIVE     │ │
│  │                                 │  │ Health: 88%      │ │
│  │  Maria: Cześć! Właśnie         │  │ RAM: 62%         │ │
│  │  skończyłam uczyć się z        │  │ CPU: 12%         │ │
│  │  3 nowych plików.              │  │ Uptime: 2h 15m   │ │
│  │                                 │  ├──────────────────┤ │
│  │  Ty: Co się nauczyłaś?         │  │ 📚 NAUKA         │ │
│  │                                 │  │ Węzły: 156       │ │
│  │  Maria: Poznałam koncepcje     │  │ Epizody: 23      │ │
│  │  meta-myślenia i...            │  │ W kolejce: 4     │ │
│  │                                 │  ├──────────────────┤ │
│  │  ⚠️ Maria: Uwaga - RAM         │  │ 🔔 ALERTY        │ │
│  │  przekroczył 80%               │  │ (brak)           │ │
│  │                                 │  │                  │ │
│  ├─────────────────────────────────┤  └──────────────────┘ │
│  │ [Napisz wiadomość...]    [Wyślij] │                     │
│  └─────────────────────────────────┘                       │
├─────────────────────────────────────────────────────────────┤
│  [▶ Start Learning] [⏸ Pause] [📊 Stats] [⚙️ Settings]    │
└─────────────────────────────────────────────────────────────┘
```

## Technologia

| Komponent | Wybór | Uzasadnienie |
|-----------|-------|--------------|
| **Backend** | Flask + Flask-SocketIO | Prosty, real-time WebSocket |
| **Frontend** | HTML/CSS/JS (vanilla) | Bez kompilacji, lekkie |
| **Komunikacja** | WebSocket | Push notifications od Marii |
| **Port** | 5000 | Standard Flask |

## Dostęp

- **Lokalnie:** `http://localhost:5000`
- **Mobilnie (WiFi):** `http://192.168.x.x:5000`

## Struktura plików

```
project/
├── maria_ui/
│   ├── __init__.py
│   ├── app.py              # Flask server + WebSocket + integracja z M.A.R.I.A.
│   ├── templates/
│   │   └── index.html      # Główny UI (single page)
│   ├── static/
│   │   ├── style.css       # Styling
│   │   └── maria.js        # WebSocket client + UI logic
│   └── api/
│       ├── __init__.py
│       ├── chat.py         # Endpoint czatu z Marią
│       ├── status.py       # Endpoint statusu homeostasis
│       └── control.py      # Start/stop/learn kontrola
├── run_ui.py               # 🎯 JEDEN PLIK DO URUCHOMIENIA
└── ...
```

## API Endpoints

### REST API

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/` | GET | Główna strona UI |
| `/api/status` | GET | Status homeostasis, RAM, CPU |
| `/api/chat` | POST | Wyślij wiadomość do Marii |
| `/api/learn/start` | POST | Uruchom naukę |
| `/api/learn/stop` | POST | Zatrzymaj naukę |
| `/api/stats` | GET | Statystyki (węzły, epizody) |

### WebSocket Events

| Event | Kierunek | Opis |
|-------|----------|------|
| `connect` | Client→Server | Połączenie |
| `chat_message` | Client→Server | Wiadomość od użytkownika |
| `chat_response` | Server→Client | Odpowiedź Marii |
| `status_update` | Server→Client | Aktualizacja statusu (co 1s) |
| `alert` | Server→Client | Powiadomienie od Marii |
| `learning_progress` | Server→Client | Postęp nauki |

## Proaktywność Marii

Maria może sama wysłać wiadomość gdy:

1. **Alerty homeostasis** - "Mój RAM przekroczył 80%"
2. **Zakończenie nauki** - "Skończyłam uczyć się z 3 plików"
3. **Zmiana trybu** - "Przechodzę w tryb SLEEP"
4. **Błędy** - "Wystąpił problem z Ollama"
5. **Ciekawe odkrycia** - "Nauczyłam się czegoś nowego o X"

## Integracja z istniejącym kodem

```python
# run_ui.py - szkic
from maria_ui.app import create_app
from agent_core.homeostasis.core import HomeostasisCore
from maria_core.memory_engine.brain_memory_integration import BrainMemoryLoop

def main():
    # 1. Inicjalizacja M.A.R.I.A. (jak w main.py)
    # 2. Start homeostasis loop
    # 3. Start Flask server
    # 4. Otwórz przeglądarkę automatycznie
    pass

if __name__ == "__main__":
    main()
```

## Fazy implementacji

### Faza 1: Podstawowy UI
- [ ] Struktura `maria_ui/`
- [ ] Flask app z jedną stroną
- [ ] Endpoint `/api/status`
- [ ] Wyświetlanie statusu homeostasis

### Faza 2: Czat
- [ ] WebSocket connection
- [ ] Endpoint czatu
- [ ] Integracja z `brain_memory_integration`
- [ ] Historia rozmowy

### Faza 3: Kontrola
- [ ] Przyciski start/stop
- [ ] Uruchamianie `/learn`
- [ ] Panel statystyk

### Faza 4: Proaktywność
- [ ] Event listener na homeostasis
- [ ] Push notifications przez WebSocket
- [ ] Alerty w UI

### Faza 5: Polish
- [ ] Responsywny design (mobile)
- [ ] Dark mode
- [ ] Auto-open browser
- [ ] Ikona w tray (opcjonalnie)

## Zależności (do dodania)

```
flask>=2.0
flask-socketio>=5.0
python-socketio>=5.0
eventlet>=0.30  # lub gevent
```

## Uruchomienie (docelowe)

```bash
# Jeden plik - uruchamia wszystko
python run_ui.py

# Otwiera się przeglądarka na http://localhost:5000
# Maria działa w tle
# Możesz rozmawiać przez UI
```

---

*Dokument roboczy - będzie rozwijany podczas implementacji*
