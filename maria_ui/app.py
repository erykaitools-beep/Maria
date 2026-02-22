"""
M.A.R.I.A. Web UI - Flask Application
Sprint 5: Proactive notifications
"""

from flask import Flask, render_template, jsonify, request, session, redirect, url_for
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
    from agent_core.homeostasis.event_logger import get_event_logger
    HOMEOSTASIS_AVAILABLE = True
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

def get_maria_brain():
    """Get or create Maria's brain instance (thread-safe)."""
    global _maria_brain
    if _maria_brain is None:
        with _brain_lock:
            if _maria_brain is None and OLLAMA_AVAILABLE:
                try:
                    _maria_brain = OllamaBrain(
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
                    print("[UI] [OK] OllamaBrain initialized")
                except Exception as e:
                    print(f"[UI] [ERROR] Could not initialize OllamaBrain: {e}")
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
                    evt_type = event.get("event", "")
                    evt_ts = event.get("timestamp", 0)

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
                    if event.get("event") == "state_snapshot":
                        snapshot_mode = event.get("mode", "ACTIVE")
                        if snapshot_mode != _last_known_mode:
                            _last_known_mode = snapshot_mode
                        break

        except Exception as e:
            print(f"[UI] [NOTIFY] [ERROR] Monitor error: {e}")

        # Wait before next check
        _notification_stop_event.wait(NOTIFICATION_CHECK_INTERVAL)

    print("[UI] [NOTIFY] Notification monitor stopped")


def start_notification_monitor():
    """Start the notification monitor thread."""
    global _notification_thread, _last_event_timestamp

    if _notification_thread is not None and _notification_thread.is_alive():
        print("[UI] [NOTIFY] Monitor already running")
        return

    # Initialize last timestamp to now to avoid old notifications
    _last_event_timestamp = time.time()
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
    return render_template('index.html')


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
                if event.get("event") == "mode_change":
                    mode = event.get("to_mode", "ACTIVE")
                    break
                elif event.get("event") == "state_snapshot":
                    mode = event.get("mode", "ACTIVE")
                    health_score = event.get("health_score", 1.0)
                    break

            if events:
                last = events[0]
                last_event = {
                    "type": last.get("event", "unknown"),
                    "timestamp": last.get("timestamp", 0)
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
    return render_template('status.html')


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
                evt_type = event.get("event", "unknown")
                ts = event.get("timestamp", 0)

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
        "memory": memory_data,
        "chat_logs_count": chat_logs_count,
        "introspection": introspection_data
    })


def _get_event_details(event):
    """Extract human-readable details from event."""
    evt_type = event.get("event", "")

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
