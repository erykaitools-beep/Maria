# M.A.R.I.A. Web UI - Specification

> **Created:** 2026-02-01
> **Status:** Planning

## Goal

A single entry point (`run_ui.py`) that launches the entire M.A.R.I.A. with a graphical web interface accessible through a browser - both locally and on mobile over WiFi.

## Requirements

1. **Single startup file** - `run_ui.py` launches everything
2. **Web UI** - runs in the browser (localhost + LAN)
3. **Chat with Maria** - real-time conversation
4. **Status panel** - health, mode, RAM, CPU, alerts
5. **Proactivity** - Maria can send a notification on her own
6. **Control** - start/stop/learn buttons

## UI Mockup

```
┌─────────────────────────────────────────────────────────────┐
│  M.A.R.I.A. Desktop                    [🟢 ACTIVE] [88%]   │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────┐  ┌──────────────────┐ │
│  │                                 │  │ 🫀 HOMEOSTASIS   │ │
│  │  💬 CHAT                        │  │ Mode: ACTIVE     │ │
│  │                                 │  │ Health: 88%      │ │
│  │  Maria: Hi! I just              │  │ RAM: 62%         │ │
│  │  finished learning from         │  │ CPU: 12%         │ │
│  │  3 new files.                   │  │ Uptime: 2h 15m   │ │
│  │                                 │  ├──────────────────┤ │
│  │  You: What did you learn?       │  │ 📚 LEARNING      │ │
│  │                                 │  │ Nodes: 156       │ │
│  │  Maria: I learned meta-         │  │ Episodes: 23     │ │
│  │  thinking concepts and...       │  │ Queued: 4        │ │
│  │                                 │  ├──────────────────┤ │
│  │  ⚠️ Maria: Warning - RAM        │  │ 🔔 ALERTS        │ │
│  │  exceeded 80%                   │  │ (none)           │ │
│  │                                 │  │                  │ │
│  ├─────────────────────────────────┤  └──────────────────┘ │
│  │ [Type a message...]      [Send] │                       │
│  └─────────────────────────────────┘                       │
├─────────────────────────────────────────────────────────────┤
│  [▶ Start Learning] [⏸ Pause] [📊 Stats] [⚙️ Settings]    │
└─────────────────────────────────────────────────────────────┘
```

## Technology

| Component | Choice | Rationale |
|-----------|-------|--------------|
| **Backend** | Flask + Flask-SocketIO | Simple, real-time WebSocket |
| **Frontend** | HTML/CSS/JS (vanilla) | No build step, lightweight |
| **Communication** | WebSocket | Push notifications from Maria |
| **Port** | 5000 | Flask default |

## Access

- **Local:** `http://localhost:5000`
- **Mobile (WiFi):** `http://192.168.x.x:5000`

## File Structure

```
project/
├── maria_ui/
│   ├── __init__.py
│   ├── app.py              # Flask server + WebSocket + M.A.R.I.A. integration
│   ├── templates/
│   │   └── index.html      # Main UI (single page)
│   ├── static/
│   │   ├── style.css       # Styling
│   │   └── maria.js        # WebSocket client + UI logic
│   └── api/
│       ├── __init__.py
│       ├── chat.py         # Maria chat endpoint
│       ├── status.py       # Homeostasis status endpoint
│       └── control.py      # Start/stop/learn control
├── run_ui.py               # 🎯 SINGLE FILE TO RUN
└── ...
```

## API Endpoints

### REST API

| Endpoint | Method | Description |
|----------|--------|------|
| `/` | GET | Main UI page |
| `/api/status` | GET | Homeostasis status, RAM, CPU |
| `/api/chat` | POST | Send a message to Maria |
| `/api/learn/start` | POST | Start learning |
| `/api/learn/stop` | POST | Stop learning |
| `/api/stats` | GET | Statistics (nodes, episodes) |

### WebSocket Events

| Event | Direction | Description |
|-------|----------|------|
| `connect` | Client→Server | Connection |
| `chat_message` | Client→Server | Message from the user |
| `chat_response` | Server→Client | Maria's response |
| `status_update` | Server→Client | Status update (every 1s) |
| `alert` | Server→Client | Notification from Maria |
| `learning_progress` | Server→Client | Learning progress |

## Maria's Proactivity

Maria can send a message on her own when:

1. **Homeostasis alerts** - "My RAM exceeded 80%"
2. **Learning completed** - "I finished learning from 3 files"
3. **Mode change** - "I'm switching to SLEEP mode"
4. **Errors** - "A problem occurred with Ollama"
5. **Interesting discoveries** - "I learned something new about X"

## Integration with Existing Code

```python
# run_ui.py - sketch
from maria_ui.app import create_app
from agent_core.homeostasis.core import HomeostasisCore
from maria_core.memory_engine.brain_memory_integration import BrainMemoryLoop

def main():
    # 1. Initialize M.A.R.I.A. (as in main.py)
    # 2. Start homeostasis loop
    # 3. Start Flask server
    # 4. Open the browser automatically
    pass

if __name__ == "__main__":
    main()
```

## Implementation Phases

### Phase 1: Basic UI
- [ ] `maria_ui/` structure
- [ ] Flask app with a single page
- [ ] `/api/status` endpoint
- [ ] Display homeostasis status

### Phase 2: Chat
- [ ] WebSocket connection
- [ ] Chat endpoint
- [ ] Integration with `brain_memory_integration`
- [ ] Conversation history

### Phase 3: Control
- [ ] Start/stop buttons
- [ ] Running `/learn`
- [ ] Statistics panel

### Phase 4: Proactivity
- [ ] Event listener on homeostasis
- [ ] Push notifications over WebSocket
- [ ] Alerts in the UI

### Phase 5: Polish
- [ ] Responsive design (mobile)
- [ ] Dark mode
- [ ] Auto-open browser
- [ ] Tray icon (optional)

## Dependencies (to add)

```
flask>=2.0
flask-socketio>=5.0
python-socketio>=5.0
eventlet>=0.30  # or gevent
```

## Running (target)

```bash
# Single file - launches everything
python run_ui.py

# The browser opens at http://localhost:5000
# Maria runs in the background
# You can chat through the UI
```

---

*Working document - will be expanded during implementation*
