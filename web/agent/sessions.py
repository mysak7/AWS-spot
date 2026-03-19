"""
Session persistence.
Layout: sessions/{host_id}/{session_id}/
  meta.json   — status, instruction, summary, timestamps
  log.jsonl   — one JSON entry per line (append-only)
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SESSIONS_DIR = Path(__file__).parent.parent.parent / "sessions"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _session_dir(host_id: str, session_id: str) -> Path:
    return SESSIONS_DIR / host_id / session_id


# ── Write ─────────────────────────────────────────────────────────────────────

def create_session(
    host_id: str,
    instruction: str,
    parent_session_id: str | None = None,
) -> str:
    session_id = uuid.uuid4().hex
    d = _session_dir(host_id, session_id)
    d.mkdir(parents=True, exist_ok=True)
    meta = {
        "session_id": session_id,
        "host_id": host_id,
        "instruction": instruction,
        "status": "running",
        "started_at": _now(),
        "finished_at": None,
        "summary": None,
        "parent_session_id": parent_session_id,
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
    (d / "log.jsonl").touch()
    return session_id


def build_context(host_id: str, session_id: str) -> str:
    """Return a text summary of a session's log suitable for use as prior context."""
    try:
        meta = load_session_meta(host_id, session_id)
        entries = read_log(host_id, session_id)
    except Exception:
        return ""

    lines = [
        f"=== Prior session context ===",
        f"Task: {meta.get('instruction', '')}",
    ]
    for e in entries:
        t = e.get("type", "")
        c = e.get("content", "").strip()
        if not c or t == "agent" and c.startswith("[finished"):
            continue
        if t == "cmd":
            lines.append(f"$ {c}")
        elif t == "output":
            # Truncate long outputs
            preview = c if len(c) <= 500 else c[:500] + "\n...(truncated)"
            lines.append(preview)
        elif t == "agent":
            lines.append(f"[agent] {c}")
        elif t == "error":
            lines.append(f"[error] {c}")

    if meta.get("summary"):
        lines.append(f"\nSession summary: {meta['summary']}")
    lines.append("=== End prior context ===\n")
    return "\n".join(lines)


def append_log(host_id: str, session_id: str, entry: dict[str, Any]) -> None:
    log_path = _session_dir(host_id, session_id) / "log.jsonl"
    line = json.dumps({"ts": _now(), **entry}) + "\n"
    with open(log_path, "a") as f:
        f.write(line)
        f.flush()


def finish_session(
    host_id: str, session_id: str, status: str, summary: str | None = None
) -> None:
    meta_path = _session_dir(host_id, session_id) / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["status"] = status
    meta["summary"] = summary
    meta["finished_at"] = _now()
    meta_path.write_text(json.dumps(meta, indent=2))


# ── Read ──────────────────────────────────────────────────────────────────────

def read_log(host_id: str, session_id: str) -> list[dict[str, Any]]:
    log_path = _session_dir(host_id, session_id) / "log.jsonl"
    if not log_path.exists():
        return []
    entries = []
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


def load_session_meta(host_id: str, session_id: str) -> dict[str, Any]:
    meta_path = _session_dir(host_id, session_id) / "meta.json"
    return json.loads(meta_path.read_text())


def load_session(host_id: str, session_id: str) -> dict[str, Any]:
    meta = load_session_meta(host_id, session_id)
    meta["log"] = read_log(host_id, session_id)
    return meta


def list_sessions(host_id: str) -> list[dict[str, Any]]:
    host_dir = SESSIONS_DIR / host_id
    if not host_dir.exists():
        return []
    sessions = []
    for d in host_dir.iterdir():
        if d.is_dir() and (d / "meta.json").exists():
            try:
                sessions.append(json.loads((d / "meta.json").read_text()))
            except Exception:
                pass
    return sorted(sessions, key=lambda s: s.get("started_at", ""), reverse=True)
