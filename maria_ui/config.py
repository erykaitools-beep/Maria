"""
M.A.R.I.A. Web UI - Configuration
Security and runtime settings
"""

import os
import secrets
from pathlib import Path

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# =============================================================================
# PATHS
# =============================================================================
PROJECT_ROOT = Path(__file__).parent.parent
UI_DIR = Path(__file__).parent
DATA_DIR = UI_DIR / "data"
CHAT_LOG_FILE = DATA_DIR / "chat_history.jsonl"

# Ensure data directory exists
DATA_DIR.mkdir(exist_ok=True)

# =============================================================================
# SECURITY SETTINGS
# =============================================================================

# PIN code for UI access (change this!)
# Can be overridden by environment variable MARIA_PIN
UI_PIN = os.environ.get("MARIA_PIN", "1234")

# Session secret key (auto-generated if not set)
SECRET_KEY = os.environ.get("MARIA_SECRET_KEY", secrets.token_hex(32))

# Rate limiting
RATE_LIMIT_MESSAGES = 2          # Max messages per window
RATE_LIMIT_WINDOW_SEC = 60       # Time window in seconds

# Input validation
MAX_MESSAGE_LENGTH = 2000        # Max characters per message
MIN_MESSAGE_LENGTH = 1           # Min characters

# =============================================================================
# CHAT SETTINGS
# =============================================================================

# Memory management
MAX_HISTORY_MESSAGES = 20        # Max messages in Ollama context
SAVE_CHAT_EVERY_N = 5            # Save to file every N messages

# Ollama timeout
OLLAMA_TIMEOUT_SEC = 120         # Max wait for response

# =============================================================================
# PRODUCTION MODE
# =============================================================================

# Set to False in production!
DEBUG_MODE = os.environ.get("MARIA_DEBUG", "false").lower() == "true"

# CORS - configurable for LAN access
# Set MARIA_CORS_ORIGINS env var to comma-separated origins, e.g.:
#   MARIA_CORS_ORIGINS=http://192.168.1.100:5000,http://192.168.1.101:5000
# Or set to * to allow all origins
def _build_cors_origins():
    """Build CORS origins list from environment or auto-detect."""
    env_origins = os.environ.get("MARIA_CORS_ORIGINS", "")
    if env_origins:
        if env_origins.strip() == "*":
            return "*"
        return [o.strip() for o in env_origins.split(",") if o.strip()]

    # Default: localhost + auto-detected LAN IP
    port = os.environ.get("MARIA_PORT", "5000")
    origins = [
        f"http://localhost:{port}",
        f"http://127.0.0.1:{port}",
    ]

    # Try to detect LAN IP for remote access
    try:
        import socket
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        if local_ip and local_ip != "127.0.0.1":
            origins.append(f"http://{local_ip}:{port}")
    except Exception:
        pass

    return origins


CORS_ORIGINS = _build_cors_origins()
