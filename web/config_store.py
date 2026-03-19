import json
from pathlib import Path

CONFIG_FILE = Path(__file__).parent.parent / "bridge_config.json"

DEFAULT_CONFIG: dict = {
    "bridge_url": "http://localhost:8001",
    "bridge_api_key": "test",
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            stored = json.loads(CONFIG_FILE.read_text())
            return {**DEFAULT_CONFIG, **stored}
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(data: dict) -> None:
    current = load_config()
    current.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
    CONFIG_FILE.write_text(json.dumps(current, indent=2))
