"""Persistent LLM query log — appends to llm_log.jsonl at project root."""
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

_LOG_PATH = Path(__file__).parent.parent / "llm_log.jsonl"
_lock = Lock()

# Pricing defaults (Claude Sonnet) — $/million tokens
INPUT_COST_PER_M = 3.0
OUTPUT_COST_PER_M = 15.0


def _cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * INPUT_COST_PER_M + output_tokens * OUTPUT_COST_PER_M) / 1_000_000


def append_query(
    *,
    host_id: str,
    session_id: str,
    step: int,
    model: str,
    input_tokens: int,
    output_tokens: int,
    duration_ms: int,
) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host_id": host_id,
        "session_id": session_id,
        "step": step,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(_cost(input_tokens, output_tokens), 8),
        "duration_ms": duration_ms,
    }
    with _lock:
        with _LOG_PATH.open("a") as f:
            f.write(json.dumps(entry) + "\n")


def load_log() -> list[dict]:
    if not _LOG_PATH.exists():
        return []
    entries = []
    with _LOG_PATH.open() as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def get_totals(entries: list[dict]) -> dict:
    total_in = sum(e["input_tokens"] for e in entries)
    total_out = sum(e["output_tokens"] for e in entries)
    return {
        "queries": len(entries),
        "input_tokens": total_in,
        "output_tokens": total_out,
        "total_tokens": total_in + total_out,
        "cost_usd": round(_cost(total_in, total_out), 6),
        "avg_duration_ms": round(sum(e["duration_ms"] for e in entries) / len(entries)) if entries else 0,
    }
