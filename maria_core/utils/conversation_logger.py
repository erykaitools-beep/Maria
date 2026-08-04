# conversation_logger.py
import json
from datetime import datetime
import os

LOG_DIR = "logs"
TEXT_LOG = os.path.join(LOG_DIR, "conversation.log")
JSON_LOG = os.path.join(LOG_DIR, "conversation.json")


def log_message(role: str, content: str):
    # Create the directory HERE, not at import. It used to run once at import
    # time, which quietly assumed the process never changes working directory
    # after that -- LOG_DIR is relative, so the dir got made in whatever cwd
    # the first import happened to see, and every later write to a different
    # cwd died with ENOENT ("No such file or directory: 'logs/conversation.log'").
    # Cheap: makedirs with exist_ok is a no-op once the dir exists.
    os.makedirs(LOG_DIR, exist_ok=True)

    timestamp = datetime.now().isoformat()

    entry = {
        "timestamp": timestamp,
        "role": role,     # "user" albo "maria"
        "content": content
    }

    # --- ZAPIS TEKSTOWY ---
    with open(TEXT_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {role.upper()}: {content}\n")

    # --- ZAPIS JSON ---
    data = []
    if os.path.exists(JSON_LOG):
        try:
            with open(JSON_LOG, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []

    data.append(entry)

    with open(JSON_LOG, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
