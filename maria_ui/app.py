"""
M.A.R.I.A. Web UI - Flask Application
Sprint 5: Proactive notifications
"""

from flask import Flask, render_template, jsonify, request, session, redirect, url_for, send_from_directory
from flask_socketio import SocketIO, emit
import sys
import time
import json
import re
import html
import psutil
import threading
from pathlib import Path
from datetime import datetime
from functools import wraps

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import config
from maria_ui.config import (
    SECRET_KEY, UI_PIN, DEBUG_MODE, CORS_ORIGINS,
    RATE_LIMIT_MESSAGES, RATE_LIMIT_WINDOW_SEC,
    MAX_MESSAGE_LENGTH, MIN_MESSAGE_LENGTH,
    MAX_HISTORY_MESSAGES, SAVE_CHAT_EVERY_N,
    CHAT_LOG_FILE
)

# Import homeostasis components (with fallback if not running)
try:
    from agent_core.homeostasis.event_logger import HomeostasisEventLogger
    HOMEOSTASIS_AVAILABLE = True

    def get_event_logger():
        """Read-only event logger for Web UI (no startup event)."""
        return HomeostasisEventLogger(log_startup=False)

except ImportError:
    HOMEOSTASIS_AVAILABLE = False

# Import OllamaBrain for chat (with fallback)
try:
    from models.ollama_brain import OllamaBrain
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

# Import introspection for code self-awareness (with fallback)
try:
    from agent_core.introspection import (
        init_introspection,
        get_introspection_scheduler,
        DualReporter,
    )
    INTROSPECTION_AVAILABLE = True
except ImportError:
    INTROSPECTION_AVAILABLE = False

# Import consciousness for identity (with fallback)
try:
    from agent_core.consciousness import IdentityStore, HumanStateMapper
    CONSCIOUSNESS_AVAILABLE = True
except ImportError:
    CONSCIOUSNESS_AVAILABLE = False

# Global identity store (lazy init)
_identity_store = None

# Global introspection scheduler (lazy init)
_introspection_scheduler = None

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Initialize SocketIO with restricted CORS
socketio = SocketIO(
    app,
    cors_allowed_origins=CORS_ORIGINS if not DEBUG_MODE else "*",
    async_mode='threading'
)

# =============================================================================
# STATE MANAGEMENT
# =============================================================================

UI_START_TIME = time.time()

# Maria's brain instance (lazy initialization)
_maria_brain = None
_brain_lock = threading.Lock()

# Rate limiting storage: {session_id: [timestamp1, timestamp2, ...]}
_rate_limit_data = {}
_rate_limit_lock = threading.Lock()

# Message counter for periodic saving
_message_counter = 0
_message_counter_lock = threading.Lock()

# UI Chat history (visible messages in browser)
# Stored per-session, separate from Ollama brain history
_ui_chat_history = []  # List of {"role": "user"|"maria"|"system", "content": "..."}
_ui_chat_lock = threading.Lock()
MAX_UI_CHAT_HISTORY = 50  # Max messages to keep in UI

# =============================================================================
# PROACTIVE NOTIFICATIONS STATE
# =============================================================================
_notification_thread = None
_notification_stop_event = threading.Event()
_last_known_mode = "ACTIVE"
_last_known_alerts_count = 0
_last_event_timestamp = 0.0
_last_planner_timestamp = 0.0
NOTIFICATION_CHECK_INTERVAL = 5  # seconds


def get_ui_chat_history():
    """Get current UI chat history."""
    with _ui_chat_lock:
        return list(_ui_chat_history)


def add_ui_chat_message(role: str, content: str):
    """Add message to UI chat history."""
    with _ui_chat_lock:
        _ui_chat_history.append({
            "role": role,
            "content": content,
            "timestamp": time.time()
        })
        # Trim if too long
        if len(_ui_chat_history) > MAX_UI_CHAT_HISTORY:
            _ui_chat_history.pop(0)


def clear_ui_chat_history():
    """Clear UI chat history."""
    with _ui_chat_lock:
        _ui_chat_history.clear()


# =============================================================================
# SECURITY HELPERS
# =============================================================================

def sanitize_input(text: str) -> str:
    """Sanitize user input to prevent XSS and injection attacks."""
    if not text:
        return ""

    # Strip whitespace
    text = text.strip()

    # Escape HTML entities
    text = html.escape(text)

    # Remove control characters (except newlines and tabs)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    # Limit length
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[:MAX_MESSAGE_LENGTH]

    return text


def validate_message(text: str):
    """Validate message content. Returns (is_valid, error_message)"""
    if not text:
        return False, "Pusta wiadomosc"

    if len(text) < MIN_MESSAGE_LENGTH:
        return False, "Wiadomosc za krotka"

    if len(text) > MAX_MESSAGE_LENGTH:
        return False, f"Wiadomosc za dluga (max {MAX_MESSAGE_LENGTH} znakow)"

    return True, ""


def check_rate_limit(session_id: str):
    """Check if session is within rate limit. Returns (is_allowed, seconds_until_reset)"""
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW_SEC

    with _rate_limit_lock:
        if session_id not in _rate_limit_data:
            _rate_limit_data[session_id] = []

        # Clean old entries
        _rate_limit_data[session_id] = [
            ts for ts in _rate_limit_data[session_id]
            if ts > window_start
        ]

        # Check limit
        if len(_rate_limit_data[session_id]) >= RATE_LIMIT_MESSAGES:
            oldest = min(_rate_limit_data[session_id])
            wait_time = int(oldest + RATE_LIMIT_WINDOW_SEC - now) + 1
            return False, wait_time

        # Add current timestamp
        _rate_limit_data[session_id].append(now)
        return True, 0


def is_authenticated() -> bool:
    """Check if current session is authenticated."""
    return session.get('authenticated', False)


def require_auth(f):
    """Decorator to require authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_authenticated():
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# =============================================================================
# CHAT LOGGING
# =============================================================================

def save_chat_message(role: str, content: str):
    """Save chat message to log file."""
    try:
        entry = {
            "timestamp": time.time(),
            "datetime": datetime.now().isoformat(),
            "role": role,
            "content": content[:500]  # Truncate for storage
        }

        with open(CHAT_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    except Exception as e:
        print(f"[UI] [WARN] Could not save chat: {e}")


def maybe_save_chat(role: str, content: str):
    """Save chat message periodically."""
    global _message_counter

    with _message_counter_lock:
        _message_counter += 1
        if _message_counter >= SAVE_CHAT_EVERY_N:
            _message_counter = 0
            save_chat_message(role, content)


# =============================================================================
# MARIA BRAIN
# =============================================================================

def _create_ui_router(brain):
    """Create LLM Router for Web UI. Returns None if NIM unavailable."""
    try:
        from maria_core.sys.config import (
            NVIDIA_NIM_API_KEY, NVIDIA_NIM_BASE_URL, NVIDIA_NIM_MODEL,
            NIM_DAILY_TOKEN_LIMIT, NIM_MONTHLY_TOKEN_LIMIT,
        )
        if not NVIDIA_NIM_API_KEY:
            return None

        from agent_core.llm import NIMClient, TokenBudget, LLMRouter

        nim = NIMClient(
            api_key=NVIDIA_NIM_API_KEY,
            model=NVIDIA_NIM_MODEL,
            base_url=NVIDIA_NIM_BASE_URL,
        )
        budget = TokenBudget(
            daily_limit=NIM_DAILY_TOKEN_LIMIT,
            monthly_limit=NIM_MONTHLY_TOKEN_LIMIT,
        )
        router = LLMRouter(
            ollama_brain=brain,
            nim_client=nim,
            token_budget=budget,
        )
        print(f"[UI] [OK] LLM Router: hybrid (NIM: {NVIDIA_NIM_MODEL} + Ollama)")
        return router
    except Exception as e:
        print(f"[UI] [WARN] LLM Router disabled: {e}")
        return None


def get_maria_brain():
    """Get or create Maria's brain instance (thread-safe)."""
    global _maria_brain
    if _maria_brain is None:
        with _brain_lock:
            if _maria_brain is None and OLLAMA_AVAILABLE:
                try:
                    brain = OllamaBrain(
                        model="llama3.1:8b",
                        system_prompt=(
                            "Jestes M.A.R.I.A. - Meta Analysis Recalibration Intelligence Architecture. "
                            "Jestes przyjazna, pomocna asystentka AI. Rozmawiasz po polsku. "
                            "Masz wlasna osobowosc - jestes ciekawa swiata, lubisz sie uczyc. "
                            "Odpowiadasz zwiezle ale cieplo. Pamietasz kontekst rozmowy. "
                            "Jesli nie znasz odpowiedzi, mowisz o tym szczerze."
                        ),
                        verify_model=False
                    )
                    # Wire state-grounded operator response pipeline
                    try:
                        from agent_core.introspection.query_router import OperationalQueryRouter
                        from agent_core.introspection.evidence_collector import EvidenceCollector
                        from agent_core.introspection.response_builder import ResponseBuilder

                        _qr = OperationalQueryRouter()
                        _ec = EvidenceCollector(project_root="/home/maria/maria")
                        _rb = ResponseBuilder()

                        # Wire LLM tape if available
                        try:
                            from agent_core.llm.llm_tape import LLMTape
                            from pathlib import Path as _Path
                            _tape = LLMTape(path=_Path("/home/maria/maria/meta_data/llm_tape.jsonl"))
                            _ec.set_llm_tape(_tape)
                            brain.set_llm_tape(_tape)
                        except Exception:
                            pass

                        brain.set_grounding_pipeline(_qr, _ec, _rb)
                        print("[UI] [OK] Grounding pipeline wired")
                    except Exception as e:
                        print(f"[UI] Grounding pipeline not available: {e}")

                    # Wrap with LLM Router if NIM available
                    router = _create_ui_router(brain)
                    _maria_brain = router if router else brain
                    print("[UI] [OK] Brain initialized")
                except Exception as e:
                    print(f"[UI] [ERROR] Could not initialize brain: {e}")
    return _maria_brain


def trim_brain_history():
    """Trim brain history to prevent memory overflow."""
    global _maria_brain

    with _brain_lock:
        if _maria_brain and len(_maria_brain.history) > MAX_HISTORY_MESSAGES + 1:
            # Keep system prompt (first) + last N messages
            system_prompt = _maria_brain.history[0]
            recent = _maria_brain.history[-(MAX_HISTORY_MESSAGES):]
            _maria_brain.history = [system_prompt] + recent
            print(f"[UI] [INFO] Trimmed history to {len(_maria_brain.history)} messages")


# =============================================================================
# PROACTIVE NOTIFICATIONS
# =============================================================================

def send_proactive_notification(notification_type: str, title: str, message: str, data: dict = None):
    """
    Send proactive notification to all connected clients.
    Types: mode_change, alert, learning_complete, system_info
    """
    notification = {
        "type": notification_type,
        "title": title,
        "message": message,
        "timestamp": time.time(),
        "data": data or {}
    }

    # Add to UI chat history as system message
    add_ui_chat_message("system", f"[{title}] {message}")

    # Emit to all connected clients
    socketio.emit('proactive_notification', notification)
    print(f"[UI] [NOTIFY] {notification_type}: {title} - {message}")


def notification_monitor_loop():
    """
    Background thread that monitors homeostasis for changes.
    Sends notifications when:
    - Mode changes (ACTIVE -> REDUCED, etc.)
    - New alerts appear
    - Learning completes (future)
    """
    global _last_known_mode, _last_known_alerts_count, _last_event_timestamp

    print("[UI] [NOTIFY] Notification monitor started")

    while not _notification_stop_event.is_set():
        try:
            if HOMEOSTASIS_AVAILABLE:
                event_logger = get_event_logger()
                events = event_logger.get_recent_events(limit=10)

                current_mode = "ACTIVE"
                new_alerts = []

                for event in events:
                    evt_type = event.get("event", event.get("event_type", ""))
                    evt_ts = event.get("timestamp", event.get("ts", 0))

                    # Skip already processed events
                    if evt_ts <= _last_event_timestamp:
                        continue

                    # Check for mode changes
                    if evt_type == "mode_change":
                        from_mode = event.get("from_mode", "?")
                        to_mode = event.get("to_mode", "?")
                        current_mode = to_mode

                        if to_mode != _last_known_mode:
                            # Mode changed - send notification
                            mode_descriptions = {
                                "ACTIVE": "System dziala normalnie",
                                "REDUCED": "Tryb oszczedzania - ograniczone zasoby",
                                "SLEEP": "Tryb uspienia - minimalna aktywnosc",
                                "SURVIVAL": "TRYB AWARYJNY - krytycznie niskie zasoby!"
                            }
                            desc = mode_descriptions.get(to_mode, "Zmiana stanu systemu")

                            # Choose notification type based on severity
                            if to_mode == "SURVIVAL":
                                notif_type = "alert"
                            elif to_mode in ["SLEEP", "REDUCED"]:
                                notif_type = "warning"
                            else:
                                notif_type = "mode_change"

                            send_proactive_notification(
                                notification_type=notif_type,
                                title=f"Zmiana trybu: {to_mode}",
                                message=desc,
                                data={"from_mode": from_mode, "to_mode": to_mode}
                            )
                            _last_known_mode = to_mode

                    # Check for alerts
                    elif evt_type == "alert":
                        severity = event.get("severity", "WARNING")
                        alert_msg = event.get("message", "Nieznany alert")

                        # Only notify on CRITICAL and ALERT severity
                        if severity in ["CRITICAL", "ALERT"]:
                            send_proactive_notification(
                                notification_type="alert",
                                title=f"Alert: {severity}",
                                message=alert_msg[:100],
                                data={"severity": severity, "full_message": alert_msg}
                            )

                    # Update last timestamp
                    if evt_ts > _last_event_timestamp:
                        _last_event_timestamp = evt_ts

                # Update mode from state_snapshot if no mode_change found
                for event in events:
                    if event.get("event", event.get("event_type")) == "state_snapshot":
                        snapshot_mode = event.get("mode", "ACTIVE")
                        if snapshot_mode != _last_known_mode:
                            _last_known_mode = snapshot_mode
                        break

        except Exception as e:
            print(f"[UI] [NOTIFY] [ERROR] Monitor error: {e}")

        # Check planner decisions
        try:
            _check_planner_notifications()
        except Exception as e:
            print(f"[UI] [NOTIFY] [ERROR] Planner monitor error: {e}")

        # Wait before next check
        _notification_stop_event.wait(NOTIFICATION_CHECK_INTERVAL)

    print("[UI] [NOTIFY] Notification monitor stopped")


def _check_planner_notifications():
    """Check planner_decisions.jsonl for new decisions and send notifications."""
    global _last_planner_timestamp

    if not _PLANNER_DECISIONS_PATH.exists():
        return

    # Read last few lines (tail approach - read all, take last few new ones)
    new_decisions = []
    try:
        with open(_PLANNER_DECISIONS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    decision = json.loads(line)
                    ts = decision.get("timestamp", 0)
                    if ts > _last_planner_timestamp:
                        new_decisions.append(decision)
                except json.JSONDecodeError:
                    continue
    except IOError:
        return

    # Notify about interesting decisions (skip NOOP and MAINTENANCE)
    NOTIFY_ACTIONS = {"learn", "exam", "review", "evaluate"}

    for decision in new_decisions:
        action = decision.get("action_type", "")
        ts = decision.get("timestamp", 0)

        if ts > _last_planner_timestamp:
            _last_planner_timestamp = ts

        if action not in NOTIFY_ACTIONS:
            continue

        message = decision.get("message", "")
        if not message:
            goal = decision.get("goal_description", "")
            message = f"{action}: {goal}" if goal else action

        success = decision.get("result", {}).get("success", False)
        status_icon = "OK" if success else "FAIL"

        send_proactive_notification(
            notification_type="planner_decision",
            title=f"Planner: {action.upper()} [{status_icon}]",
            message=message[:150],
            data={"action": action, "success": success}
        )


def start_notification_monitor():
    """Start the notification monitor thread."""
    global _notification_thread, _last_event_timestamp, _last_planner_timestamp

    if _notification_thread is not None and _notification_thread.is_alive():
        print("[UI] [NOTIFY] Monitor already running")
        return

    # Initialize last timestamp to now to avoid old notifications
    _last_event_timestamp = time.time()
    _last_planner_timestamp = time.time()
    _notification_stop_event.clear()

    _notification_thread = threading.Thread(
        target=notification_monitor_loop,
        daemon=True,
        name="NotificationMonitor"
    )
    _notification_thread.start()


def stop_notification_monitor():
    """Stop the notification monitor thread."""
    global _notification_thread

    _notification_stop_event.set()
    if _notification_thread is not None:
        _notification_thread.join(timeout=2)
        _notification_thread = None
        print("[UI] [NOTIFY] Monitor stopped")


# =============================================================================
# ROUTES
# =============================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page with PIN."""
    error = None

    if request.method == 'POST':
        pin = request.form.get('pin', '')

        if pin == UI_PIN:
            session['authenticated'] = True
            session.permanent = True
            return redirect(url_for('index'))
        else:
            error = "Nieprawidlowy PIN"

    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    """Logout and clear session."""
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@require_auth
def index():
    """Main page - chat interface."""
    return render_template('index.html', active_page='chat')


@app.route('/api/status')
@require_auth
def api_status():
    """API endpoint: Real system status from homeostasis."""
    memory = psutil.virtual_memory()
    cpu_percent = psutil.cpu_percent(interval=0.1)

    uptime_sec = time.time() - UI_START_TIME
    if uptime_sec < 60:
        uptime_str = f"{uptime_sec:.0f}s"
    elif uptime_sec < 3600:
        uptime_str = f"{uptime_sec/60:.1f}m"
    else:
        uptime_str = f"{uptime_sec/3600:.1f}h"

    mode = "ACTIVE"
    last_event = None
    health_score = 1.0

    if HOMEOSTASIS_AVAILABLE:
        try:
            event_logger = get_event_logger()
            events = event_logger.get_recent_events(limit=5)

            for event in events:
                if event.get("event", event.get("event_type")) == "mode_change":
                    mode = event.get("to_mode", "ACTIVE")
                    break
                elif event.get("event", event.get("event_type")) == "state_snapshot":
                    mode = event.get("mode", "ACTIVE")
                    health_score = event.get("health_score", 1.0)
                    break

            if events:
                last = events[0]
                last_event = {
                    "type": last.get("event", last.get("event_type", "unknown")),
                    "timestamp": last.get("timestamp", last.get("ts", 0))
                }
        except Exception as e:
            print(f"[UI] [WARN] Could not read homeostasis: {e}")

    mode_messages = {
        "ACTIVE": "System dziala w pelni sprawnie",
        "REDUCED": "Tryb oszczedzania zasobow",
        "SLEEP": "Tryb uspienia - minimalna aktywnosc",
        "SURVIVAL": "Tryb awaryjny - krytycznie niskie zasoby"
    }
    message = mode_messages.get(mode, "System aktywny")

    # Get brain history count
    brain = get_maria_brain()
    history_count = len(brain.history) - 1 if brain else 0

    status = {
        "alive": True,
        "name": "M.A.R.I.A.",
        "version": "4.0",
        "mode": mode,
        "message": message,
        "metrics": {
            "ram_percent": memory.percent,
            "ram_available_gb": memory.available / (1024**3),
            "cpu_percent": cpu_percent,
            "uptime": uptime_str,
            "uptime_sec": uptime_sec
        },
        "health_score": health_score,
        "last_event": last_event,
        "homeostasis_connected": HOMEOSTASIS_AVAILABLE,
        "ollama_connected": OLLAMA_AVAILABLE,
        "chat_history_count": history_count
    }
    return jsonify(status)


@app.route('/api/health')
def api_health():
    """Health check endpoint (no auth required)."""
    return jsonify({"status": "ok"})


@app.route('/api/chat/history')
@require_auth
def api_chat_history():
    """Get UI chat history for restoring after page navigation."""
    return jsonify({
        "messages": get_ui_chat_history()
    })


@app.route('/api/notify/test', methods=['POST'])
@require_auth
def api_notify_test():
    """
    API endpoint: Send a test notification.
    Used for testing the notification system.
    """
    send_proactive_notification(
        notification_type="system_info",
        title="Test powiadomienia",
        message="To jest testowe powiadomienie z API!",
        data={"test": True}
    )
    return jsonify({"success": True, "message": "Test notification sent"})


@app.route('/api/notify/send', methods=['POST'])
@require_auth
def api_notify_send():
    """
    API endpoint: Send custom notification.
    Body: {"type": "info|warning|alert", "title": "...", "message": "..."}
    """
    data = request.get_json() or {}
    notif_type = data.get("type", "system_info")
    title = sanitize_input(data.get("title", "Powiadomienie"))
    message = sanitize_input(data.get("message", ""))

    if not message:
        return jsonify({"success": False, "error": "Message is required"}), 400

    send_proactive_notification(
        notification_type=notif_type,
        title=title,
        message=message[:200],
        data=data.get("data", {})
    )
    return jsonify({"success": True})


@app.route('/status')
@require_auth
def status_page():
    """Full status dashboard page."""
    return render_template('status.html', active_page='status')


@app.route('/api/status/full')
@require_auth
def api_status_full():
    """
    API endpoint: Full system status with all metrics.
    Used by the status dashboard.
    """
    # System metrics
    memory = psutil.virtual_memory()
    cpu_percent = psutil.cpu_percent(interval=0.1)
    disk = psutil.disk_usage('/')

    # Uptime
    uptime_sec = time.time() - UI_START_TIME
    system_boot = psutil.boot_time()
    system_uptime_sec = time.time() - system_boot

    def format_uptime(sec):
        if sec < 60:
            return f"{sec:.0f}s"
        elif sec < 3600:
            return f"{sec/60:.1f}m"
        elif sec < 86400:
            return f"{sec/3600:.1f}h"
        else:
            return f"{sec/86400:.1f}d"

    # Homeostasis data
    homeostasis_data = {
        "connected": HOMEOSTASIS_AVAILABLE,
        "mode": "ACTIVE",
        "health_score": 1.0,
        "recent_events": [],
        "mode_changes_count": 0,
        "alerts": {"CRITICAL": 0, "ALERT": 0, "WARNING": 0}
    }

    if HOMEOSTASIS_AVAILABLE:
        try:
            event_logger = get_event_logger()
            events = event_logger.get_recent_events(limit=20)

            # Process events
            for event in events:
                evt_type = event.get("event", event.get("event_type", "unknown"))
                ts = event.get("timestamp", event.get("ts", 0))

                # Get current mode
                if evt_type == "mode_change" and homeostasis_data["mode"] == "ACTIVE":
                    homeostasis_data["mode"] = event.get("to_mode", "ACTIVE")
                    homeostasis_data["mode_changes_count"] += 1
                elif evt_type == "state_snapshot" and homeostasis_data["health_score"] == 1.0:
                    homeostasis_data["mode"] = event.get("mode", "ACTIVE")
                    homeostasis_data["health_score"] = event.get("health_score", 1.0)

                # Count alerts
                if evt_type == "alert":
                    severity = event.get("severity", "WARNING")
                    if severity in homeostasis_data["alerts"]:
                        homeostasis_data["alerts"][severity] += 1

                # Add to recent events (max 10)
                if len(homeostasis_data["recent_events"]) < 10:
                    homeostasis_data["recent_events"].append({
                        "type": evt_type,
                        "timestamp": ts,
                        "datetime": datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "-",
                        "details": _get_event_details(event)
                    })

        except Exception as e:
            print(f"[UI] [WARN] Could not read homeostasis: {e}")

    # Brain/Chat data
    brain = get_maria_brain()
    brain_data = {
        "connected": OLLAMA_AVAILABLE,
        "model": "llama3.1:8b",
        "history_count": len(brain.history) - 1 if brain else 0,
        "call_count": brain.call_count if brain else 0
    }

    # Memory files data
    memory_data = _get_memory_stats()

    # Chat logs
    chat_logs_count = 0
    if CHAT_LOG_FILE.exists():
        try:
            with open(CHAT_LOG_FILE, 'r', encoding='utf-8') as f:
                chat_logs_count = sum(1 for _ in f)
        except:
            pass

    # Introspection data (code self-awareness)
    introspection_data = {
        "available": INTROSPECTION_AVAILABLE,
        "files": 0,
        "lines": 0,
        "functions": 0,
        "classes": 0,
        "issues_count": 0,
        "last_analysis": None
    }

    if INTROSPECTION_AVAILABLE:
        try:
            scheduler = _get_introspection_scheduler()
            if scheduler:
                model = scheduler.get_model()
                if model:
                    introspection_data.update({
                        "files": model.total_files,
                        "lines": model.total_lines,
                        "functions": model.total_functions,
                        "classes": model.total_classes,
                        "issues_count": len(model.issues),
                        "last_analysis": model.analysis_timestamp.isoformat() if model.analysis_timestamp else None
                    })
        except Exception as e:
            print(f"[UI] [WARN] Could not get introspection data: {e}")

    # NIM / LLM Router data
    nim_data = {
        "available": False,
        "backend": "ollama",
        "nim_model": None,
        "ollama_model": "llama3.1:8b",
        "nim_calls": 0,
        "ollama_calls": 0,
        "nim_fallbacks": 0,
        "total_calls": 0,
        "budget": {
            "status": "N/A",
            "daily_used": 0,
            "daily_limit": 0,
            "daily_percent": 0,
            "monthly_used": 0,
            "monthly_limit": 0,
            "monthly_percent": 0,
        }
    }

    if brain and hasattr(brain, "get_stats") and hasattr(brain, "get_active_backend"):
        try:
            stats = brain.get_stats()
            budget_info = stats.get("budget", {})
            daily = budget_info.get("daily", {})
            monthly = budget_info.get("monthly", {})
            daily_limit = daily.get("limit", 0)
            monthly_limit = monthly.get("limit", 0)

            nim_data.update({
                "available": stats.get("nim_available", False),
                "backend": stats.get("active_backend", "ollama"),
                "nim_model": stats.get("nim_model"),
                "nim_calls": stats.get("nim_calls", 0),
                "ollama_calls": stats.get("ollama_calls", 0),
                "nim_fallbacks": stats.get("nim_fallbacks", 0),
                "total_calls": stats.get("total_calls", 0),
                "budget": {
                    "status": budget_info.get("status", "N/A"),
                    "daily_used": daily.get("used", 0),
                    "daily_limit": daily_limit,
                    "daily_percent": (daily.get("used", 0) / daily_limit * 100) if daily_limit > 0 else 0,
                    "monthly_used": monthly.get("used", 0),
                    "monthly_limit": monthly_limit,
                    "monthly_percent": (monthly.get("used", 0) / monthly_limit * 100) if monthly_limit > 0 else 0,
                }
            })
        except Exception as e:
            print(f"[UI] [WARN] Could not get NIM data: {e}")

    # Identity / Consciousness data
    identity_data = _get_identity_data()

    # Planner data
    planner_data = _get_planner_data()

    # --- New v2 Metaoperator data ---
    models_data = _get_models_data()
    openclaw_data = _get_openclaw_data()
    goals_data = _get_goals_summary()
    cognitive_data = _get_cognitive_counts()
    integrity_data = _get_memory_integrity_flags()
    event_stream = _get_unified_events(30)
    traits_data = _get_traits_data()

    # Homeostasis cause (WHY)
    raw_events = []
    if HOMEOSTASIS_AVAILABLE:
        try:
            raw_events = get_event_logger().get_recent_events(limit=10)
        except Exception:
            pass
    homeostasis_data["cause"] = _get_homeostasis_cause(
        homeostasis_data.get("mode", "ACTIVE"), raw_events
    )

    # Extend memory with cognitive counts and integrity
    memory_data["cognitive"] = cognitive_data
    memory_data["integrity"] = integrity_data

    # Extend identity with traits
    identity_data["traits"] = traits_data

    return jsonify({
        "timestamp": time.time(),
        "system": {
            "ram": {
                "percent": memory.percent,
                "used_gb": memory.used / (1024**3),
                "available_gb": memory.available / (1024**3),
                "total_gb": memory.total / (1024**3)
            },
            "cpu": {
                "percent": cpu_percent,
                "cores": psutil.cpu_count()
            },
            "disk": {
                "percent": disk.percent,
                "used_gb": disk.used / (1024**3),
                "free_gb": disk.free / (1024**3),
                "total_gb": disk.total / (1024**3)
            },
            "uptime": {
                "ui_sec": uptime_sec,
                "ui_formatted": format_uptime(uptime_sec),
                "system_sec": system_uptime_sec,
                "system_formatted": format_uptime(system_uptime_sec)
            }
        },
        "homeostasis": homeostasis_data,
        "brain": brain_data,
        "nim": nim_data,
        "identity": identity_data,
        "memory": memory_data,
        "planner": planner_data,
        "models": models_data,
        "openclaw": openclaw_data,
        "goals": goals_data,
        "event_stream": event_stream,
        "chat_logs_count": chat_logs_count,
        "introspection": introspection_data,
        "learning_queue": _get_learning_queue()
    })


def _get_event_details(event):
    """Extract human-readable details from event."""
    evt_type = event.get("event", event.get("event_type", ""))

    if evt_type == "mode_change":
        return f"{event.get('from_mode', '?')} -> {event.get('to_mode', '?')}"
    elif evt_type == "alert":
        return f"{event.get('severity', '?')}: {event.get('message', '')[:50]}"
    elif evt_type == "state_snapshot":
        return f"Health: {event.get('health_score', 0):.0%}"
    elif evt_type == "startup":
        return "System started"
    elif evt_type == "shutdown":
        return f"Reason: {event.get('reason', '?')}"

    return ""


def _get_identity_store():
    """Get or create identity store (lazy init, read-only for UI)."""
    global _identity_store

    if _identity_store is None and CONSCIOUSNESS_AVAILABLE:
        try:
            _identity_store = IdentityStore(data_dir=str(PROJECT_ROOT / "meta_data"))
            print("[UI] [OK] Identity store loaded")
        except Exception as e:
            print(f"[UI] [WARN] Could not load identity: {e}")

    return _identity_store


def _get_identity_data():
    """Get identity data for API response."""
    identity_data = {
        "available": CONSCIOUSNESS_AVAILABLE,
        "name": "M.A.R.I.A.",
        "full_name": "Meta Analysis Recalibration Intelligence Architecture",
        "birth_date": None,
        "session_count": 0,
        "total_uptime_hours": 0,
        "restart_count": 0,
        "primary_user": None,
        "last_session_summary": "",
        "feeling": None,
    }

    if CONSCIOUSNESS_AVAILABLE:
        store = _get_identity_store()
        if store:
            try:
                d = store.get_identity_dict()
                identity_data.update({
                    "name": d.get("full_name", "M.A.R.I.A."),
                    "full_name": d.get("full_name_expanded", ""),
                    "birth_date": d.get("birth_date"),
                    "session_count": d.get("session_count", 0),
                    "total_uptime_hours": d.get("total_uptime_hours", 0),
                    "restart_count": d.get("restart_count", 0),
                    "primary_user": d.get("primary_user"),
                    "last_session_summary": d.get("last_session_summary", ""),
                })
            except Exception as e:
                print(f"[UI] [WARN] Could not get identity data: {e}")

        # Get feeling
        try:
            mapper = HumanStateMapper()
            identity_data["feeling"] = mapper.describe_feeling()
        except Exception:
            pass

    return identity_data


# Planner data paths
_PLANNER_STATE_PATH = PROJECT_ROOT / "meta_data" / "planner_state.json"
_PLANNER_DECISIONS_PATH = PROJECT_ROOT / "meta_data" / "planner_decisions.jsonl"


def _get_planner_data():
    """Get planner data from files (no SharedContext needed)."""
    planner_data = {
        "available": False,
        "total_cycles": 0,
        "total_plans": 0,
        "last_decision": None,
    }

    # Read planner state
    if _PLANNER_STATE_PATH.exists():
        try:
            with open(_PLANNER_STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
            planner_data["available"] = True
            planner_data["total_cycles"] = state.get("total_cycles", 0)
            planner_data["total_plans"] = state.get("total_plans_executed", 0)
        except (IOError, json.JSONDecodeError):
            pass

    # Read last decision from JSONL
    if _PLANNER_DECISIONS_PATH.exists():
        try:
            last_line = ""
            with open(_PLANNER_DECISIONS_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        last_line = line.strip()
            if last_line:
                decision = json.loads(last_line)
                planner_data["available"] = True
                planner_data["last_decision"] = {
                    "action": decision.get("action_type", "?"),
                    "goal": decision.get("goal_description", ""),
                    "status": decision.get("status", "?"),
                    "success": decision.get("result", {}).get("success", False),
                    "message": decision.get("message", ""),
                    "timestamp": decision.get("timestamp", 0),
                    "datetime": (
                        datetime.fromtimestamp(decision["timestamp"]).strftime("%H:%M:%S")
                        if decision.get("timestamp") else "-"
                    ),
                }
        except (IOError, json.JSONDecodeError):
            pass

    return planner_data


def _get_introspection_scheduler():
    """Get or create introspection scheduler (lazy init)."""
    global _introspection_scheduler

    if _introspection_scheduler is None and INTROSPECTION_AVAILABLE:
        try:
            _introspection_scheduler = init_introspection(
                project_root=str(PROJECT_ROOT),
                start_scheduler=False,  # On-demand only
            )
            print("[UI] [OK] Introspection scheduler initialized")
        except Exception as e:
            print(f"[UI] [WARN] Could not init introspection: {e}")

    return _introspection_scheduler


@app.route('/api/introspect')
@require_auth
def api_introspect():
    """
    API endpoint: Get Maria's code self-awareness data.
    Returns human summary + technical stats about her own architecture.
    """
    if not INTROSPECTION_AVAILABLE:
        return jsonify({
            "success": False,
            "error": "Introspection not available"
        }), 503

    scheduler = _get_introspection_scheduler()
    if not scheduler:
        return jsonify({
            "success": False,
            "error": "Could not initialize introspection"
        }), 500

    # Get or run analysis
    model = scheduler.get_model()
    if model is None:
        # First time - run analysis
        model = scheduler.run_now()

    if model is None:
        return jsonify({
            "success": False,
            "error": "Analysis failed"
        }), 500

    # Generate reports
    reporter = DualReporter(model)
    human_summary, tech_summary = reporter.full_report()

    return jsonify({
        "success": True,
        "human_summary": human_summary,
        "tech_summary": tech_summary,
        "statistics": model.get_statistics(),
        "layers": model.layers,
        "packages": list(model.packages.keys()),
        "last_analysis": model.analysis_timestamp.isoformat() if model.analysis_timestamp else None
    })


@app.route('/api/introspect/issues')
@require_auth
def api_introspect_issues():
    """API endpoint: Get code issues found by introspection."""
    if not INTROSPECTION_AVAILABLE:
        return jsonify({"success": False, "error": "Introspection not available"}), 503

    scheduler = _get_introspection_scheduler()
    if not scheduler:
        return jsonify({"success": False, "error": "Could not initialize"}), 500

    model = scheduler.get_model()
    if model is None:
        model = scheduler.run_now()

    if model is None:
        return jsonify({"success": False, "error": "Analysis failed"}), 500

    issues = [issue.to_dict() for issue in model.issues]

    return jsonify({
        "success": True,
        "total": len(issues),
        "issues": issues[:50],  # Limit to 50
        "by_type": model.get_statistics().get("issues", {}).get("by_type", {}),
        "by_severity": model.get_statistics().get("issues", {}).get("by_severity", {})
    })


@app.route('/api/introspect/refresh', methods=['POST'])
@require_auth
def api_introspect_refresh():
    """API endpoint: Force refresh of code analysis."""
    if not INTROSPECTION_AVAILABLE:
        return jsonify({"success": False, "error": "Introspection not available"}), 503

    scheduler = _get_introspection_scheduler()
    if not scheduler:
        return jsonify({"success": False, "error": "Could not initialize"}), 500

    # Force new analysis
    model = scheduler.run_now()

    if model is None:
        return jsonify({"success": False, "error": "Analysis failed"}), 500

    return jsonify({
        "success": True,
        "message": "Analysis refreshed",
        "files": model.total_files,
        "lines": model.total_lines,
        "timestamp": model.analysis_timestamp.isoformat()
    })


def _get_learning_queue():
    """Get learning queue status from knowledge_index.jsonl."""
    result = {
        "available": False,
        "total": 0,
        "completed": 0,
        "learning": 0,
        "new": 0,
        "hard_topic": 0,
        "exam_failed": 0,
        "learned": 0,
        "files": []
    }

    try:
        from agent_core.awareness import ContextBuilder
        cb = ContextBuilder()
        files = cb.get_detailed_file_list()

        if not files:
            return result

        result["available"] = True
        result["total"] = len(files)

        for f in files:
            status = f.get("status", "other")
            if status in result:
                result[status] += 1

        # Sort: completed first, then learning, then new
        order = ["completed", "learned", "learning", "new", "hard_topic", "exam_failed"]
        result["files"] = sorted(
            files,
            key=lambda r: order.index(r.get("status", "other"))
                          if r.get("status", "other") in order else 99
        )
    except Exception as e:
        print(f"[UI] [WARN] Could not get learning queue: {e}")

    return result


def _get_memory_stats():
    """Get statistics about Maria's memory files."""
    stats = {
        "semantic_graph": {"nodes": 0, "edges": 0, "size_kb": 0},
        "knowledge_index": {"entries": 0, "size_kb": 0},
        "longterm_memory": {"entries": 0, "size_kb": 0}
    }

    # Semantic graph
    sg_path = PROJECT_ROOT / "semantic_graph.json"
    if sg_path.exists():
        try:
            stats["semantic_graph"]["size_kb"] = sg_path.stat().st_size / 1024
            with open(sg_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                stats["semantic_graph"]["nodes"] = len(data.get("nodes", {}))
                stats["semantic_graph"]["edges"] = len(data.get("edges", []))
        except:
            pass

    # Knowledge index
    ki_path = PROJECT_ROOT / "memory" / "knowledge_index.jsonl"
    if ki_path.exists():
        try:
            stats["knowledge_index"]["size_kb"] = ki_path.stat().st_size / 1024
            with open(ki_path, 'r', encoding='utf-8') as f:
                stats["knowledge_index"]["entries"] = sum(1 for line in f if line.strip())
        except:
            pass

    # Longterm memory
    ltm_path = PROJECT_ROOT / "memory" / "maria_longterm_memory.jsonl"
    if ltm_path.exists():
        try:
            stats["longterm_memory"]["size_kb"] = ltm_path.stat().st_size / 1024
            with open(ltm_path, 'r', encoding='utf-8') as f:
                stats["longterm_memory"]["entries"] = sum(1 for line in f if line.strip())
        except:
            pass

    return stats


# =============================================================================
# NEW DATA HELPERS FOR METAOPERATOR PANEL (v2)
# =============================================================================

def _get_models_data():
    """Get model registry specs + scheduler status for Metaoperator Panel."""
    result = {
        "registry": [],
        "scheduler": {
            "loaded_models": {},
            "loaded_count": 0,
            "total_loaded_ram_gb": 0,
            "free_ram_gb": 0,
            "ram_pressure_events": 0,
        },
    }

    # Registry (static model specs)
    try:
        from agent_core.llm.model_registry import list_models
        for spec in list_models():
            result["registry"].append({
                "role": spec.role.value,
                "model_id": spec.model_id,
                "ollama_tag": spec.ollama_tag,
                "ram_estimate_gb": spec.ram_estimate_gb,
                "warm_state": spec.warm_state.value,
                "concurrency_class": spec.concurrency_class.value,
                "fallback_role": spec.fallback_role.value if spec.fallback_role else None,
                "latency_budget_s": spec.latency_budget_s,
            })
    except Exception as e:
        print(f"[UI] [WARN] Could not read model registry: {e}")

    # Scheduler status (from persisted health file)
    health_path = PROJECT_ROOT / "meta_data" / "model_health.json"
    if health_path.exists():
        try:
            with open(health_path, 'r', encoding='utf-8') as f:
                health = json.load(f)
            result["scheduler"]["ram_pressure_events"] = health.get("ram_pressure_events", 0)
            models = health.get("models", {})
            result["scheduler"]["loaded_models"] = models
            result["scheduler"]["loaded_count"] = len(models)
            total_ram = sum(
                m.get("ram_estimate_gb", 0) for m in models.values()
                if m.get("healthy", True)
            )
            result["scheduler"]["total_loaded_ram_gb"] = round(total_ram, 1)
        except (IOError, json.JSONDecodeError):
            pass

    # Free RAM from psutil
    try:
        result["scheduler"]["free_ram_gb"] = round(
            psutil.virtual_memory().available / (1024**3), 1
        )
    except Exception:
        pass

    return result


# OpenClaw cache
_openclaw_cache = None
_openclaw_cache_ts = 0
_OPENCLAW_CACHE_TTL = 10  # seconds


def _get_openclaw_data():
    """Get OpenClaw effector status.

    Uses lightweight process check instead of full health_check() to avoid
    loading the OpenClaw agent model (qwen2.5:3b) which consumes 3GB RAM
    and 6 CPU cores. Full health_check() goes through gateway->node->exec
    pipeline and keeps the model warm.
    """
    global _openclaw_cache, _openclaw_cache_ts

    now = time.time()
    if _openclaw_cache and (now - _openclaw_cache_ts) < _OPENCLAW_CACHE_TTL:
        return _openclaw_cache

    result = {
        "connected": False,
        "node_name": "maria",
        "total_calls": 0,
        "successful_calls": 0,
        "failed_calls": 0,
        "last_error": None,
    }

    # Lightweight check: is the OpenClaw gateway process running?
    # This avoids triggering model loading via nodes run / agent commands.
    import subprocess as _sp
    try:
        check = _sp.run(
            ["pgrep", "-f", "openclaw.*gateway"],
            capture_output=True, timeout=2,
        )
        result["connected"] = check.returncode == 0
    except Exception:
        pass

    # Stats from client (does NOT trigger subprocess, just returns in-memory counters)
    try:
        from agent_core.effector.openclaw_client import OpenClawClient
        client = OpenClawClient()
        stats = client.get_stats()
        result["node_name"] = stats.get("node_name", "maria")
        result["total_calls"] = stats.get("total_calls", 0)
        result["successful_calls"] = stats.get("successful_calls", 0)
        result["failed_calls"] = stats.get("failed_calls", 0)
        result["last_error"] = stats.get("last_error")
    except Exception:
        pass

    _openclaw_cache = result
    _openclaw_cache_ts = now
    return result


def _get_goals_summary():
    """Get goal counts from goals.jsonl (MERGE semantics: last record per id wins)."""
    result = {"active_count": 0, "proposed_count": 0, "completed_count": 0, "total": 0}

    goals_path = PROJECT_ROOT / "meta_data" / "goals.jsonl"
    if not goals_path.exists():
        return result

    try:
        goals_by_id = {}
        with open(goals_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    g = json.loads(line)
                    gid = g.get("id") or g.get("goal_id", "")
                    if gid:
                        goals_by_id[gid] = g.get("status", "")
                except json.JSONDecodeError:
                    continue

        result["total"] = len(goals_by_id)
        for status in goals_by_id.values():
            s = status.upper()
            if s in ("ACTIVE", "PENDING"):
                result["active_count"] += 1
            elif s == "PROPOSED":
                result["proposed_count"] += 1
            elif s in ("COMPLETED", "ACHIEVED"):
                result["completed_count"] += 1
    except IOError:
        pass

    return result


def _get_cognitive_counts():
    """Count records in K6-K10 JSONL files."""
    counts = {"beliefs": 0, "reflections": 0, "action_audit": 0, "autonomy_decisions": 0}
    files_map = {
        "beliefs": "beliefs.jsonl",
        "reflections": "reflections.jsonl",
        "action_audit": "action_audit.jsonl",
        "autonomy_decisions": "autonomy_decisions.jsonl",
    }
    for key, filename in files_map.items():
        path = PROJECT_ROOT / "meta_data" / filename
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    counts[key] = sum(1 for line in f if line.strip())
            except IOError:
                pass
    return counts


def _get_memory_integrity_flags():
    """Raw boolean flags for memory integrity heuristic (computed in JS)."""
    flags = {
        "has_graph_nodes": False,
        "has_longterm": False,
        "has_knowledge": False,
        "has_reflections": False,
        "last_memory_update_ts": None,
    }

    # Semantic graph
    sg_path = PROJECT_ROOT / "semantic_graph.json"
    if sg_path.exists():
        try:
            with open(sg_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            flags["has_graph_nodes"] = len(data.get("nodes", {})) > 0
            flags["last_memory_update_ts"] = sg_path.stat().st_mtime
        except Exception:
            pass

    # Knowledge index
    ki_path = PROJECT_ROOT / "memory" / "knowledge_index.jsonl"
    if ki_path.exists():
        try:
            flags["has_knowledge"] = ki_path.stat().st_size > 100
            mtime = ki_path.stat().st_mtime
            if flags["last_memory_update_ts"] is None or mtime > flags["last_memory_update_ts"]:
                flags["last_memory_update_ts"] = mtime
        except Exception:
            pass

    # Longterm memory
    ltm_path = PROJECT_ROOT / "memory" / "maria_longterm_memory.jsonl"
    if ltm_path.exists():
        try:
            flags["has_longterm"] = ltm_path.stat().st_size > 100
        except Exception:
            pass

    # Reflections
    refl_path = PROJECT_ROOT / "meta_data" / "reflections.jsonl"
    if refl_path.exists():
        try:
            flags["has_reflections"] = refl_path.stat().st_size > 100
        except Exception:
            pass

    return flags


def _get_unified_events(limit=30):
    """Merge recent events from multiple JSONL sources into unified timeline."""
    events = []

    # Homeostasis events
    if HOMEOSTASIS_AVAILABLE:
        try:
            event_logger = get_event_logger()
            for evt in event_logger.get_recent_events(limit=15):
                evt_type = evt.get("event", evt.get("event_type", "unknown"))
                ts = evt.get("timestamp", evt.get("ts", 0))
                events.append({
                    "source": "homeostasis",
                    "type": evt_type,
                    "timestamp": ts,
                    "details": _get_event_details(evt),
                    "severity": "warning" if evt_type == "alert" else "info",
                })
        except Exception:
            pass

    # Planner decisions
    if _PLANNER_DECISIONS_PATH.exists():
        try:
            last_lines = []
            with open(_PLANNER_DECISIONS_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        last_lines.append(line.strip())
            for line in last_lines[-15:]:
                try:
                    d = json.loads(line)
                    action = d.get("action_type", "")
                    ts = d.get("timestamp", 0)
                    success = d.get("result", {}).get("success", False)
                    msg = d.get("message", "")[:100]
                    events.append({
                        "source": "planner",
                        "type": action,
                        "timestamp": ts,
                        "details": msg or f"{action} ({'OK' if success else 'FAIL'})",
                        "severity": "ok" if success else "warning",
                    })
                except json.JSONDecodeError:
                    continue
        except IOError:
            pass

    # Action audit (last few)
    audit_path = PROJECT_ROOT / "meta_data" / "action_audit.jsonl"
    if audit_path.exists():
        try:
            last_lines = []
            with open(audit_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        last_lines.append(line.strip())
            for line in last_lines[-10:]:
                try:
                    a = json.loads(line)
                    ts = a.get("timestamp", 0)
                    action = a.get("action_type", "")
                    safety = a.get("safety_mode", "")
                    success = a.get("success", False)
                    events.append({
                        "source": "safety",
                        "type": f"{action}/{safety}",
                        "timestamp": ts,
                        "details": f"{'OK' if success else 'FAIL'} [{safety}]",
                        "severity": "ok" if success else "warning",
                    })
                except json.JSONDecodeError:
                    continue
        except IOError:
            pass

    # Sort by timestamp descending, take limit
    events.sort(key=lambda e: e.get("timestamp", 0), reverse=True)
    return events[:limit]


def _get_homeostasis_cause(mode, recent_events):
    """Derive WHY for current homeostasis mode from recent events."""
    if mode == "ACTIVE":
        return "no issue"
    if mode == "SLEEP":
        return "consolidation phase"

    # Look for alerts in recent events
    for evt in recent_events:
        evt_type = evt.get("event", evt.get("event_type", ""))
        if evt_type == "alert":
            msg = evt.get("message", "")
            if "ram" in msg.lower() or "memory" in msg.lower():
                return "ram pressure"
            if "cpu" in msg.lower():
                return "cpu overload"
            if "token" in msg.lower():
                return "token depletion"
            if "temp" in msg.lower():
                return "thermal throttle"
            return msg[:60] if msg else "alert triggered"

    if mode == "REDUCED":
        return "resource conservation"
    if mode == "SURVIVAL":
        return "critical resources"
    return "unknown"


def _get_traits_data():
    """Get personality trait scores from consciousness identity."""
    traits = {}
    identity_path = PROJECT_ROOT / "meta_data" / "consciousness_identity.json"
    if identity_path.exists():
        try:
            with open(identity_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            trait_scores = data.get("trait_scores", {})
            for name, info in trait_scores.items():
                if isinstance(info, dict):
                    traits[name] = round(info.get("score", 0), 2)
                else:
                    traits[name] = round(float(info), 2)
        except Exception:
            pass
    return traits


# =============================================================================
# WEBSOCKET EVENTS
# =============================================================================

@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    # Check authentication via session
    if not is_authenticated():
        print("[UI] [SOCKET] Unauthorized connection attempt")
        return False  # Reject connection

    print("[UI] [SOCKET] Client connected")
    emit('connected', {
        'message': 'Polaczono z M.A.R.I.A.',
        'ollama_available': OLLAMA_AVAILABLE,
        'rate_limit': {
            'messages': RATE_LIMIT_MESSAGES,
            'window_sec': RATE_LIMIT_WINDOW_SEC
        }
    })


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    print("[UI] [SOCKET] Client disconnected")


@socketio.on('chat_message')
def handle_chat_message(data):
    """Handle incoming chat message from user."""
    # Get session ID for rate limiting
    session_id = request.sid

    # Check rate limit
    allowed, wait_time = check_rate_limit(session_id)
    if not allowed:
        emit('chat_response', {
            'success': False,
            'error': f'Limit wiadomosci. Poczekaj {wait_time}s.',
            'rate_limited': True,
            'wait_seconds': wait_time
        })
        return

    # Get and sanitize message
    raw_message = data.get('message', '')
    user_message = sanitize_input(raw_message)

    # Validate
    is_valid, error = validate_message(user_message)
    if not is_valid:
        emit('chat_response', {
            'success': False,
            'error': error
        })
        return

    print(f"[UI] [CHAT] User: {user_message[:50]}...")

    # Save user message to UI history
    add_ui_chat_message("user", user_message)

    # Save to file periodically
    maybe_save_chat("user", user_message)

    # Emit "thinking" status
    emit('chat_status', {'status': 'thinking'})

    # Get response from Maria
    brain = get_maria_brain()

    if brain is None:
        fallback_msg = (
            "Przepraszam, moj mozg (Ollama) nie jest teraz dostepny. "
            "Sprawdz czy Ollama jest uruchomiona na localhost:11434."
        )
        # Save fallback response to UI history
        add_ui_chat_message("maria", fallback_msg)

        emit('chat_response', {
            'success': True,
            'message': fallback_msg,
            'fallback': True
        })
        return

    # Conversation-Driven Learning: detect learning intent before chat
    try:
        from agent_core.perception.learning_intent import detect_learning_intent
        intent = detect_learning_intent(user_message)
        if intent:
            _topic = intent["topic"]
            _action = intent["action"]
            # Create goal directly via GoalStore (Web UI is separate process)
            try:
                from agent_core.goals.goal_model import GoalType, GoalStatus, create_goal
                from agent_core.goals.store import GoalStore
                from pathlib import Path as _GPath
                _gs = GoalStore(goals_path=_GPath("meta_data/goals.jsonl"))
                _gs.load()
                _g = create_goal(
                    goal_type=GoalType.LEARNING,
                    description=f"Nauka: {_topic}",
                    priority=0.8,
                    status=GoalStatus.PENDING,
                    created_by="user_conversation",
                    metadata={
                        "source": "conversation",
                        "channel": "webui",
                        "action": _action,
                        "topic": _topic,
                        "topics": [_topic],
                        "original_text": user_message[:200],
                    },
                )
                _gs.create(_g)
                _gs.save()
                emit('chat_status', {
                    'status': 'learning_detected',
                    'topic': _topic,
                    'action': _action,
                })
                print(f"[UI] [CDL] Learning intent: {_action} '{_topic}'")
            except Exception as e:
                print(f"[UI] [CDL] Goal creation failed: {e}")
    except Exception:
        pass

    try:
        # Get response from Ollama
        response = brain.think(user_message)

        # Trim history if needed
        trim_brain_history()

        if response:
            print(f"[UI] [CHAT] Maria: {response[:50]}...")

            # Save Maria's response to UI history
            add_ui_chat_message("maria", response)

            # Save to file periodically
            maybe_save_chat("maria", response)

            emit('chat_response', {
                'success': True,
                'message': response,
                'fallback': False
            })
        else:
            emit('chat_response', {
                'success': False,
                'error': 'Brak odpowiedzi od Ollamy'
            })

    except Exception as e:
        print(f"[UI] [ERROR] Chat error: {e}")
        emit('chat_response', {
            'success': False,
            'error': 'Blad komunikacji z Ollama'
        })


@socketio.on('clear_history')
def handle_clear_history():
    """Clear Maria's conversation history (both brain and UI)."""
    global _maria_brain

    # Clear Ollama brain history
    with _brain_lock:
        if _maria_brain:
            _maria_brain.history = [_maria_brain.history[0]]
            print("[UI] [CHAT] Brain history cleared")

    # Clear UI chat history
    clear_ui_chat_history()
    print("[UI] [CHAT] UI history cleared")

    emit('history_cleared', {'success': True})


# =============================================================================
# MAIN
# =============================================================================

# =============================================================================
# ARCHITECTURE MAP (READ-ONLY)
# =============================================================================

_architecture_cache = None
_architecture_cache_ts = 0

# JSONL data flow: which module reads/writes which files
# This is static knowledge about the architecture, not runtime data
_JSONL_DATA_FLOW = {
    "meta_data/homeostasis_events.jsonl": {
        "writers": ["agent_core.homeostasis.core"],
        "readers": ["agent_core.evaluation.observer", "agent_core.storage"],
        "label": "System state snapshots",
    },
    "meta_data/goals.jsonl": {
        "writers": ["agent_core.goals.store"],
        "readers": ["agent_core.planner.planner_core"],
        "label": "Goal system",
    },
    "meta_data/planner_decisions.jsonl": {
        "writers": ["agent_core.planner.planner_core"],
        "readers": ["agent_core.evaluation.observer"],
        "label": "Planner decisions",
    },
    "meta_data/planner_state.json": {
        "writers": ["agent_core.planner.planner_core"],
        "readers": ["agent_core.planner.planner_core"],
        "label": "Planner checkpoint",
    },
    "meta_data/deliberation_intents.jsonl": {
        "writers": ["agent_core.deliberation.intent_tracker"],
        "readers": ["agent_core.deliberation.deliberator"],
        "label": "Multi-step strategies (K8)",
    },
    "meta_data/beliefs.jsonl": {
        "writers": ["agent_core.world_model.belief_store"],
        "readers": ["agent_core.world_model.query", "agent_core.planner.planner_core"],
        "label": "World model beliefs (K6)",
    },
    "meta_data/reflections.jsonl": {
        "writers": ["agent_core.meta_cognition.reflection_store"],
        "readers": ["agent_core.meta_cognition.reflector"],
        "label": "Self-reflection (K9)",
    },
    "meta_data/action_audit.jsonl": {
        "writers": ["agent_core.action_safety.audit_log"],
        "readers": ["agent_core.action_safety"],
        "label": "Action safety audit (K10)",
    },
    "meta_data/autonomy_decisions.jsonl": {
        "writers": ["agent_core.autonomy.escalation"],
        "readers": ["agent_core.autonomy"],
        "label": "Autonomy policy (K7)",
    },
    "meta_data/teacher_plans.jsonl": {
        "writers": ["agent_core.teacher.teacher_agent"],
        "readers": ["agent_core.evaluation.observer"],
        "label": "Teacher execution log",
    },
    "meta_data/web_fetch_registry.jsonl": {
        "writers": ["agent_core.web_source.fetch_registry"],
        "readers": ["agent_core.web_source.topic_suggester"],
        "label": "Web fetch dedup",
    },
    "meta_data/evaluation_reports.jsonl": {
        "writers": ["agent_core.evaluation.observer"],
        "readers": ["agent_core.planner.planner_core"],
        "label": "K4 evaluation reports",
    },
    "meta_data/experiment_proposals.jsonl": {
        "writers": ["agent_core.experiment.proposal_engine"],
        "readers": ["agent_core.experiment"],
        "label": "K11 experiment proposals",
    },
    "meta_data/experiment_reports.jsonl": {
        "writers": ["agent_core.experiment"],
        "readers": ["agent_core.experiment"],
        "label": "K11 experiment reports",
    },
    "memory/knowledge_index.jsonl": {
        "writers": ["maria_core.learning"],
        "readers": ["agent_core.teacher.knowledge_analyzer", "agent_core.world_model.belief_builder"],
        "label": "Knowledge index (legacy)",
    },
    "memory/exam_results.jsonl": {
        "writers": ["maria_core.learning"],
        "readers": ["agent_core.evaluation.observer"],
        "label": "Exam results",
    },
}

# Decision pipeline (ordered steps)
_DECISION_PIPELINE = [
    {"id": "sense", "label": "SENSE", "module": "agent_core.homeostasis.core", "phase": 1,
     "description": "Read sensors: RAM, CPU, disk, temperature, idle time"},
    {"id": "interpret", "label": "INTERPRET", "module": "agent_core.homeostasis.interpreter", "phase": 2,
     "description": "Convert raw metrics to semantic state"},
    {"id": "validate", "label": "VALIDATE", "module": "agent_core.homeostasis.constraints", "phase": 3,
     "description": "Check constraints, generate alerts"},
    {"id": "mode", "label": "DECIDE MODE", "module": "agent_core.homeostasis.mode_regulator", "phase": 4,
     "description": "ACTIVE / REDUCED / SLEEP / SURVIVAL"},
    {"id": "perceive", "label": "PERCEIVE", "module": "agent_core.perception.buffer", "phase": 8,
     "description": "Aggregate events into PerceptionBuffer (K1)"},
    {"id": "guard", "label": "GUARD", "module": "agent_core.planner.planner_guard", "phase": 10,
     "description": "Can planning happen? Health, mode, sandbox, retention"},
    {"id": "context", "label": "GATHER CONTEXT", "module": "agent_core.planner.planner_core", "phase": 10,
     "description": "Read K4 metrics, K6 beliefs, K9 confidence"},
    {"id": "goal", "label": "SELECT GOAL", "module": "agent_core.planner.goal_selector", "phase": 10,
     "description": "Pick best goal by priority with aging factor"},
    {"id": "deliberate", "label": "DELIBERATE", "module": "agent_core.deliberation.deliberator", "phase": 10,
     "description": "Multi-step strategy from K8 templates"},
    {"id": "plan", "label": "CREATE PLAN", "module": "agent_core.planner.planner_core", "phase": 10,
     "description": "Map goal+strategy to single-step Plan"},
    {"id": "k7_check", "label": "K7 CHECK", "module": "agent_core.autonomy", "phase": 10,
     "description": "Rate limit + policy rules + classification"},
    {"id": "k10_before", "label": "K10 BEFORE", "module": "agent_core.action_safety", "phase": 10,
     "description": "Classify safety, capture before-state"},
    {"id": "execute", "label": "EXECUTE", "module": "agent_core.planner.action_executor", "phase": 10,
     "description": "Delegate to Teacher/Sandbox/WebSource/Experiment"},
    {"id": "k9_reflect", "label": "K9 REFLECT", "module": "agent_core.meta_cognition.reflector", "phase": 10,
     "description": "Compare expected vs actual outcome"},
    {"id": "k6_update", "label": "K6 UPDATE", "module": "agent_core.world_model", "phase": 10,
     "description": "Update beliefs after exam/evaluate"},
]


def _build_architecture_data():
    """Build architecture data using CodeAnalyzer. Cached for 5 min."""
    global _architecture_cache, _architecture_cache_ts
    import time as _time

    now = _time.time()
    if _architecture_cache and (now - _architecture_cache_ts) < 300:
        return _architecture_cache

    try:
        from agent_core.introspection.analyzer import CodeAnalyzer
        analyzer = CodeAnalyzer(str(PROJECT_ROOT))
        model = analyzer.analyze()

        # Build package groups (agent_core.planner -> planner)
        packages = {}
        for pkg_name, module_info in model.modules.items():
            parts = pkg_name.split(".")
            if len(parts) >= 2 and parts[0] == "agent_core":
                group = parts[1]
            elif parts[0] == "maria_core":
                group = "maria_core"
            elif parts[0] == "maria_ui":
                group = "maria_ui"
            else:
                group = parts[0]

            if group not in packages:
                packages[group] = {
                    "name": group,
                    "files": [],
                    "total_lines": 0,
                    "total_functions": 0,
                    "total_classes": 0,
                }

            file_data = {
                "package": pkg_name,
                "file": module_info.relative_path,
                "lines": module_info.line_count,
                "docstring": (module_info.docstring or "")[:200],
                "functions": [
                    {"name": f.name, "line": f.line_start, "params": f.parameters,
                     "doc": (f.docstring or "")[:100]}
                    for f in module_info.functions
                ],
                "classes": [
                    {"name": c.name, "line": c.line_start, "methods": [m.name for m in c.methods],
                     "doc": (c.docstring or "")[:100]}
                    for c in module_info.classes
                ],
            }
            packages[group]["files"].append(file_data)
            packages[group]["total_lines"] += module_info.line_count
            packages[group]["total_functions"] += module_info.function_count
            packages[group]["total_classes"] += module_info.class_count

        # Build dependency edges (only internal)
        edges = []
        seen = set()
        for dep in model.dependencies:
            # Normalize to group level
            from_parts = dep.from_module.split(".")
            to_parts = dep.to_module.split(".")

            if len(from_parts) >= 2 and from_parts[0] == "agent_core":
                from_group = from_parts[1]
            else:
                from_group = from_parts[0]

            if len(to_parts) >= 2 and to_parts[0] == "agent_core":
                to_group = to_parts[1]
            else:
                to_group = to_parts[0]

            # Skip self-edges and external
            if from_group == to_group:
                continue
            if from_group not in packages or to_group not in packages:
                continue

            key = f"{from_group}->{to_group}"
            if key not in seen:
                seen.add(key)
                edges.append({
                    "from": from_group,
                    "to": to_group,
                    "type": "import",
                })

        result = {
            "packages": packages,
            "edges": edges,
            "data_flow": _JSONL_DATA_FLOW,
            "pipeline": _DECISION_PIPELINE,
            "stats": model.get_statistics(),
        }

        _architecture_cache = result
        _architecture_cache_ts = now
        return result

    except Exception as e:
        return {"error": str(e), "packages": {}, "edges": [], "data_flow": {}, "pipeline": [], "stats": {}}


@app.route('/architecture')
@require_auth
def architecture_page():
    """Architecture map page."""
    return render_template('architecture.html', active_page='architecture')


@app.route('/api/architecture')
@require_auth
def api_architecture():
    """Get full architecture data for interactive map."""
    data = _build_architecture_data()
    return jsonify(data)


@app.route('/api/architecture/package/<name>')
@require_auth
def api_architecture_package(name):
    """Get detailed info about a specific package."""
    data = _build_architecture_data()
    pkg = data.get("packages", {}).get(name)
    if pkg is None:
        return jsonify({"error": f"Package '{name}' not found"}), 404
    return jsonify(pkg)


# =============================================================================
# EXPERIMENT SYSTEM (K11)
# =============================================================================

# Lazy import for experiment system
_experiment_system = None

def _get_experiment_system():
    """Get or create ExperimentSystem instance."""
    global _experiment_system
    if _experiment_system is None:
        try:
            from agent_core.experiment import ExperimentSystem
            _experiment_system = ExperimentSystem()
        except ImportError:
            pass
    return _experiment_system


@app.route('/experiments')
@require_auth
def experiments_page():
    """Experiment dashboard page."""
    return render_template('experiments.html', active_page='experiments')


@app.route('/api/experiments/proposals')
@require_auth
def api_experiment_proposals():
    """Get all proposals."""
    system = _get_experiment_system()
    if system is None:
        return jsonify({"error": "Experiment system not available"}), 503

    proposals = system.proposal_engine.get_all_proposals()
    return jsonify([p.to_dict() for p in proposals])


@app.route('/api/experiments/reports')
@require_auth
def api_experiment_reports():
    """Get all reports."""
    system = _get_experiment_system()
    if system is None:
        return jsonify({"error": "Experiment system not available"}), 503

    reports = system.get_all_reports()
    return jsonify([r.to_dict() for r in reports])


@app.route('/api/experiments/reports/<report_id>')
@require_auth
def api_experiment_report_detail(report_id):
    """Get single report."""
    system = _get_experiment_system()
    if system is None:
        return jsonify({"error": "Experiment system not available"}), 503

    report = system.get_report(report_id)
    if report is None:
        return jsonify({"error": "Report not found"}), 404
    return jsonify(report.to_dict())


@app.route('/api/experiments/approve/<proposal_id>', methods=['POST'])
@require_auth
def api_experiment_approve(proposal_id):
    """Approve a proposal."""
    system = _get_experiment_system()
    if system is None:
        return jsonify({"error": "Experiment system not available"}), 503

    if system.approve(proposal_id):
        return jsonify({"success": True, "message": f"Proposal {proposal_id} approved"})
    return jsonify({"success": False, "message": "Approval failed"}), 400


@app.route('/api/experiments/reject/<proposal_id>', methods=['POST'])
@require_auth
def api_experiment_reject(proposal_id):
    """Reject a proposal."""
    system = _get_experiment_system()
    if system is None:
        return jsonify({"error": "Experiment system not available"}), 503

    if system.reject(proposal_id):
        return jsonify({"success": True, "message": f"Proposal {proposal_id} rejected"})
    return jsonify({"success": False, "message": "Rejection failed"}), 400


@app.route('/api/experiments/comment/<proposal_id>', methods=['POST'])
@require_auth
def api_experiment_comment(proposal_id):
    """Add comment to a proposal."""
    system = _get_experiment_system()
    if system is None:
        return jsonify({"error": "Experiment system not available"}), 503

    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"success": False, "message": "Empty comment"}), 400

    # Sanitize
    text = html.escape(text)[:500]

    if system.add_comment(proposal_id, text, "user"):
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Comment failed"}), 400


@app.route('/api/experiments/status')
@require_auth
def api_experiment_status():
    """Get experiment system status."""
    system = _get_experiment_system()
    if system is None:
        return jsonify({"error": "Experiment system not available"}), 503

    return jsonify(system.get_status())


@app.route('/api/experiments/params')
@require_auth
def api_experiment_params():
    """Get tunable parameters."""
    try:
        from agent_core.experiment import parameter_registry
        params = parameter_registry.list_parameters()
        result = []
        for pid, spec in params.items():
            result.append({
                "param_id": pid,
                "module_path": spec.module_path,
                "constant_name": spec.constant_name,
                "current_value": spec.current_value,
                "value_type": spec.value_type,
                "min_value": spec.min_value,
                "max_value": spec.max_value,
                "step": spec.step,
                "risk_level": spec.risk_level.value,
                "impact_metric": spec.impact_metric,
                "description": spec.description,
            })
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "Experiment module not available"}), 503


@app.route('/api/experiments/export/<report_id>')
@require_auth
def api_experiment_export(report_id):
    """Export report as JSON download."""
    system = _get_experiment_system()
    if system is None:
        return jsonify({"error": "Experiment system not available"}), 503

    report = system.get_report(report_id)
    if report is None:
        return jsonify({"error": "Report not found"}), 404

    from flask import Response
    data = json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
    return Response(
        data,
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename={report_id}.json'},
    )


# =============================================
# K12 Self-Analysis page
# =============================================

@app.route('/traces')
@require_auth
def traces_page():
    """Decision Traces dashboard page (Phase 1)."""
    return render_template('traces.html', active_page='traces')


@app.route('/analysis')
@require_auth
def analysis_page():
    """Self-Analysis dashboard page."""
    return render_template('analysis.html', active_page='analysis')


def _read_analysis_reports():
    """Read all analysis reports from JSONL."""
    import os
    reports_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "meta_data", "self_analysis_reports.jsonl"
    )
    results = []
    try:
        with open(reports_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    results.append(json.loads(line))
    except (IOError, json.JSONDecodeError):
        pass
    return results


@app.route('/api/analysis/latest')
@require_auth
def api_analysis_latest():
    """Get most recent analysis report."""
    reports = _read_analysis_reports()
    if not reports:
        return jsonify({"error": "No reports available"}), 404
    return jsonify(reports[-1])


@app.route('/api/analysis/recommendations')
@require_auth
def api_analysis_recommendations():
    """Get recommendations from latest report."""
    reports = _read_analysis_reports()
    if not reports:
        return jsonify([])
    return jsonify(reports[-1].get("recommendations", []))


@app.route('/api/analysis/history')
@require_auth
def api_analysis_history():
    """Get all historical reports (summarized)."""
    reports = _read_analysis_reports()
    result = []
    for r in reports:
        result.append({
            "report_id": r.get("report_id"),
            "timestamp": r.get("timestamp"),
            "analyzer": r.get("analyzer"),
            "num_recommendations": len(r.get("recommendations", [])),
            "num_goals": len(r.get("goals_created", [])),
            "duration_ms": r.get("duration_ms"),
            "error": r.get("error"),
        })
    return jsonify(result[-20:])  # Last 20


@app.route('/api/analysis/status')
@require_auth
def api_analysis_status():
    """Get K12 system status."""
    reports = _read_analysis_reports()
    last = reports[-1] if reports else None
    return jsonify({
        "available": bool(reports),
        "total_reports": len(reports),
        "last_report_id": last.get("report_id") if last else None,
        "last_analyzer": last.get("analyzer") if last else None,
        "last_timestamp": last.get("timestamp") if last else None,
    })


# =============================================================
# Decision Traces API (Phase 1 traceability)
# =============================================================

def _read_traces(limit=50):
    """Read recent decision traces from JSONL."""
    import os
    traces_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "meta_data", "decision_traces.jsonl"
    )
    results = []
    try:
        with open(traces_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except IOError:
        pass
    # Return most recent first
    return list(reversed(results[-limit:]))


# =============================================================
# Memory Query API (Phase 2 - unified knowledge)
# =============================================================

@app.route('/api/memory/query')
@require_auth
def api_memory_query():
    """Query Maria's knowledge about a topic."""
    topic = request.args.get('topic', '').strip()
    if not topic:
        return jsonify({"error": "Missing 'topic' parameter"}), 400

    try:
        from agent_core.memory.query import MemoryQuery
        mq = MemoryQuery()
        results = mq.query_topic(topic, top_k=10)
        summary = mq.get_topic_summary(topic)
        return jsonify({
            "topic": topic,
            "summary": summary,
            "results": [r.to_dict() for r in results],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/memory/gaps')
@require_auth
def api_memory_gaps():
    """Get knowledge gaps (low confidence topics)."""
    try:
        from agent_core.memory.query import MemoryQuery
        mq = MemoryQuery()
        gaps = mq.get_knowledge_gaps(top_k=10)
        return jsonify({"gaps": gaps, "count": len(gaps)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/traces')
@require_auth
def api_traces():
    """Get recent decision traces."""
    limit = request.args.get('limit', 20, type=int)
    traces = _read_traces(limit=min(limit, 100))
    return jsonify({"traces": traces, "count": len(traces)})


@app.route('/api/traces/<episode_id>')
@require_auth
def api_trace_detail(episode_id):
    """Get a specific trace by episode_id."""
    traces = _read_traces(limit=200)
    for t in traces:
        if t.get("episode_id") == episode_id:
            return jsonify(t)
    return jsonify({"error": "not found"}), 404


@app.route('/api/traces/stats')
@require_auth
def api_traces_stats():
    """Get aggregate stats from recent traces."""
    traces = _read_traces(limit=100)
    if not traces:
        return jsonify({"total": 0})

    total = len(traces)
    success = sum(1 for t in traces if t.get("success") is True)
    failed = sum(1 for t in traces if t.get("success") is False)
    durations = [t.get("duration_ms", 0) for t in traces if t.get("duration_ms", 0) > 0]
    avg_dur = round(sum(durations) / len(durations), 1) if durations else 0.0
    llm_calls = sum(t.get("total_llm_calls", 0) for t in traces)
    k7_blocks = sum(1 for t in traces if t.get("k7_decision") in ("block", "rate_limited"))

    action_counts = {}
    for t in traces:
        a = t.get("action_type") or "unknown"
        action_counts[a] = action_counts.get(a, 0) + 1

    return jsonify({
        "total": total,
        "success": success,
        "failed": failed,
        "avg_duration_ms": avg_dur,
        "total_llm_calls": llm_calls,
        "k7_blocks": k7_blocks,
        "action_types": action_counts,
    })


@app.route('/api/traces/failed')
@require_auth
def api_traces_failed():
    """Get recent failed traces."""
    limit = request.args.get('limit', 10, type=int)
    traces = _read_traces(limit=100)
    failed = [t for t in traces if t.get("success") is False]
    return jsonify({"traces": failed[:limit], "count": len(failed[:limit])})


# =============================================================
# Belief Store v2 API
# =============================================================


def _read_beliefs():
    """Read current beliefs from JSONL."""
    import os
    beliefs_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "meta_data", "beliefs.jsonl"
    )
    beliefs = {}
    try:
        with open(beliefs_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                        beliefs[rec["belief_id"]] = rec
                    except (json.JSONDecodeError, KeyError):
                        pass
    except IOError:
        pass
    # Return only current (non-superseded)
    return [b for b in beliefs.values() if not b.get("superseded_by")]


@app.route('/api/beliefs/stats')
@require_auth
def api_beliefs_stats():
    """Get belief store stats."""
    beliefs = _read_beliefs()
    if not beliefs:
        return jsonify({"total": 0})

    by_type = {}
    by_entity_type = {}
    total_conf = 0.0
    total_evidence = 0

    for b in beliefs:
        bt = b.get("belief_type", "?")
        by_type[bt] = by_type.get(bt, 0) + 1
        et = b.get("entity_type", "?")
        by_entity_type[et] = by_entity_type.get(et, 0) + 1
        total_conf += b.get("confidence", 0)
        total_evidence += len(b.get("evidence", []))

    return jsonify({
        "total": len(beliefs),
        "avg_confidence": round(total_conf / len(beliefs), 3) if beliefs else 0,
        "total_evidence": total_evidence,
        "by_belief_type": by_type,
        "by_entity_type": by_entity_type,
    })


@app.route('/api/beliefs/gaps')
@require_auth
def api_beliefs_gaps():
    """Get knowledge gaps (lowest confidence topics)."""
    beliefs = _read_beliefs()
    topics = {}
    for b in beliefs:
        if b.get("entity_type") == "topic":
            entity = b.get("entity", "?")
            conf = b.get("confidence", 0)
            if entity not in topics or conf < topics[entity]:
                topics[entity] = conf

    gaps = sorted(topics.items(), key=lambda x: x[1])[:15]
    return jsonify({
        "gaps": [{"topic": t, "confidence": c} for t, c in gaps],
        "count": len(gaps),
    })


@app.route('/api/beliefs/recent')
@require_auth
def api_beliefs_recent():
    """Get most recently updated beliefs."""
    beliefs = _read_beliefs()
    beliefs.sort(key=lambda b: b.get("updated_at", 0), reverse=True)
    limit = request.args.get('limit', 20, type=int)
    return jsonify({"beliefs": beliefs[:limit], "count": min(limit, len(beliefs))})


# =============================================================
# Cross-Validation API (Faza F - Multi-Source Learning)
# =============================================================


def _read_disputes(limit=50):
    """Read recent disputes from JSONL."""
    import os
    disputes_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "meta_data", "dispute_log.jsonl"
    )
    results = []
    try:
        with open(disputes_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except IOError:
        pass
    return list(reversed(results[-limit:]))


@app.route('/validation')
@require_auth
def validation_page():
    """Cross-Validation dashboard page (Faza F)."""
    return render_template('validation.html', active_page='validation')


@app.route('/api/validation/stats')
@require_auth
def api_validation_stats():
    """Get cross-validation stats."""
    try:
        from agent_core.cross_validation import CrossValidator
        # Try to get stats from running instance via SharedContext
        # Fallback: read from dispute log
        disputes = _read_disputes(limit=500)
        total_disputes = len(disputes)
        unresolved = sum(1 for d in disputes if not d.get("resolution"))

        # Count validations from traces
        traces = _read_traces(limit=200)
        validations = [t for t in traces if t.get("action_type") == "validate"]
        total_validated = len(validations)
        successful = sum(1 for v in validations if v.get("success") is True)

        # Calculate avg confidence from validation results
        confidences = []
        for v in validations:
            params = v.get("action_params", {})
            # Also check result for avg_confidence
            result = v.get("result_summary", "")
            if isinstance(v.get("steps"), list):
                for step in v["steps"]:
                    detail = step.get("detail", {})
                    if "avg_confidence" in detail:
                        confidences.append(detail["avg_confidence"])

        return jsonify({
            "total_validations": total_validated,
            "successful": successful,
            "total_disputes": total_disputes,
            "unresolved_disputes": unresolved,
            "avg_confidence": round(sum(confidences) / len(confidences), 3) if confidences else 0,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/validation/disputes')
@require_auth
def api_validation_disputes():
    """Get recent cross-validation disputes."""
    limit = request.args.get('limit', 30, type=int)
    disputes = _read_disputes(limit=min(limit, 100))
    return jsonify({"disputes": disputes, "count": len(disputes)})


@app.route('/api/validation/disputes/unresolved')
@require_auth
def api_validation_disputes_unresolved():
    """Get unresolved disputes."""
    disputes = _read_disputes(limit=500)
    unresolved = [d for d in disputes if not d.get("resolution")]
    return jsonify({"disputes": unresolved, "count": len(unresolved)})


@app.route('/api/validation/history')
@require_auth
def api_validation_history():
    """Get validation action history from traces."""
    limit = request.args.get('limit', 20, type=int)
    traces = _read_traces(limit=200)
    validations = [t for t in traces if t.get("action_type") == "validate"]
    return jsonify({"validations": validations[:limit], "count": len(validations[:limit])})


# =============================================================
# Document Downloads (PDF status reports, etc.)
# =============================================================

DOCS_DIR = PROJECT_ROOT / "docs"


@app.route('/api/docs')
@require_auth
def api_docs_list():
    """List available documents (PDF/MD) in docs/."""
    files = []
    for f in sorted(DOCS_DIR.iterdir()):
        if f.suffix in ('.pdf', '.md') and f.is_file():
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "type": f.suffix[1:],
            })
    return jsonify({"files": files, "count": len(files)})


@app.route('/api/docs/download/<filename>')
@require_auth
def api_docs_download(filename):
    """Download a document from docs/."""
    # Security: only allow files from docs/ directory, no path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        return jsonify({"error": "Invalid filename"}), 400
    filepath = DOCS_DIR / filename
    if not filepath.exists() or not filepath.is_file():
        return jsonify({"error": "File not found"}), 404
    return send_from_directory(str(DOCS_DIR), filename, as_attachment=True)


if __name__ == '__main__':
    print("=" * 50)
    print("[START] M.A.R.I.A. Web UI (Sprint 5)")
    print("=" * 50)
    print(f"Debug mode: {DEBUG_MODE}")
    print(f"Ollama available: {OLLAMA_AVAILABLE}")
    print(f"Homeostasis available: {HOMEOSTASIS_AVAILABLE}")
    print(f"Rate limit: {RATE_LIMIT_MESSAGES} msg / {RATE_LIMIT_WINDOW_SEC}s")
    print(f"PIN: {UI_PIN}")
    print()
    print("Open in browser: http://localhost:5000")
    print("Press Ctrl+C to stop")
    print("=" * 50)

    # Start notification monitor
    start_notification_monitor()

    try:
        socketio.run(
            app,
            host='0.0.0.0',
            port=5000,
            debug=DEBUG_MODE,
            allow_unsafe_werkzeug=True
        )
    finally:
        # Clean shutdown
        stop_notification_monitor()
