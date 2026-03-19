import json
import os
import pwd
import subprocess
import time
from collections.abc import Callable
from threading import Event
from typing import Any

from llm_log import append_query

CLAUDE_BIN_DEFAULT = "node /usr/lib/node_modules/@anthropic-ai/claude-code/cli.js"
CLAUDE_USER = "claudeuser"  # non-root user to run claude (root is blocked)


def _drop_to_claude_user() -> None:
    """preexec_fn: switch to claudeuser so claude allows --dangerously-skip-permissions."""
    try:
        pw = pwd.getpwnam(CLAUDE_USER)
        os.setgid(pw.pw_gid)
        os.setuid(pw.pw_uid)
        os.environ["HOME"] = pw.pw_dir
    except (KeyError, PermissionError):
        pass  # user doesn't exist or already non-root — proceed anyway

TASK_PROMPT = """\
You are controlling a remote EC2 instance via SSH.

Host IP: {public_ip}
SSH key: {key_file}
SSH user: ec2-user

To run commands on the remote host use:
  ssh -i {key_file} -o StrictHostKeyChecking=no -o BatchMode=yes ec2-user@{public_ip} 'your command'

For multiple commands in one call use:
  ssh -i {key_file} -o StrictHostKeyChecking=no ec2-user@{public_ip} 'bash -s' <<'EOF'
  command1
  command2
  EOF

Task: {instruction}
"""


def _parse_stream(
    line: str,
    on_log: Callable[[dict[str, Any]], None],
    host_id: str,
    session_id: str,
) -> dict | None:
    """Parse one stream-json line. Returns the result event or None."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        if line.strip():
            on_log({"type": "agent", "content": line.strip()})
        return None

    etype = event.get("type")

    if etype == "assistant":
        for block in event.get("message", {}).get("content", []):
            btype = block.get("type")
            if btype == "text" and block.get("text", "").strip():
                on_log({"type": "agent", "content": block["text"].strip()})
            elif btype == "tool_use" and block.get("name") == "Bash":
                cmd = block.get("input", {}).get("command", "").strip()
                if cmd:
                    on_log({"type": "cmd", "content": cmd})

    elif etype == "user":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_result":
                content = block.get("content", "")
                if isinstance(content, list):
                    text = "\n".join(
                        c.get("text", "") for c in content if c.get("type") == "text"
                    )
                else:
                    text = str(content)
                if text.strip():
                    on_log({"type": "output", "content": text.rstrip()})

    elif etype == "result":
        input_tok = event.get("input_tokens", 0) or 0
        output_tok = event.get("output_tokens", 0) or 0
        duration = event.get("duration_ms", 0) or 0
        if input_tok or output_tok:
            append_query(
                host_id=host_id,
                session_id=session_id,
                step=0,
                model="claude-code",
                input_tokens=input_tok,
                output_tokens=output_tok,
                duration_ms=duration,
            )
        return event

    elif etype == "system" and event.get("subtype") == "error":
        on_log({"type": "error", "content": event.get("error", {}).get("message", str(event))})

    return None


def run_agent(
    host: dict[str, Any],
    instruction: str,
    on_log: Callable[[dict[str, Any]], None],
    claude_bin: str = CLAUDE_BIN_DEFAULT,
    session_id: str = "",
    stop_event: Event | None = None,
    **_kwargs: Any,  # absorb legacy bridge_url / bridge_api_key if passed
) -> tuple[str, str]:
    """Run claude locally to control the remote host via SSH.
    Returns (summary, final_status) where final_status is done|failed|stopped.
    """
    host_id = host.get("host_id", "unknown")
    prompt = TASK_PROMPT.format(
        public_ip=host.get("public_ip", ""),
        key_file=host.get("key_file", ""),
        instruction=instruction,
    )

    cmd = claude_bin.split() + [
        "-p", prompt,
        "--output-format", "stream-json",
        "--allowedTools", "Bash",
        "--max-turns", "30",
        "--dangerously-skip-permissions",
    ]

    t0 = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            preexec_fn=_drop_to_claude_user,
        )
    except FileNotFoundError as e:
        msg = f"claude binary not found: {claude_bin}"
        on_log({"type": "error", "content": msg})
        return msg, "failed"

    result_event: dict | None = None
    final_status = "done"

    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            if stop_event and stop_event.is_set():
                proc.terminate()
                on_log({"type": "error", "content": "Stopped by user."})
                final_status = "stopped"
                break
            ev = _parse_stream(line, on_log, host_id, session_id)
            if ev is not None:
                result_event = ev

        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()

    # Capture any stderr (e.g. auth errors, node crashes)
    stderr = proc.stderr.read() if proc.stderr else ""  # type: ignore[union-attr]
    if stderr.strip():
        on_log({"type": "error", "content": stderr.strip()})

    if final_status == "done":
        if proc.returncode not in (0, None):
            final_status = "failed"
        elif result_event and result_event.get("subtype") == "error_during_execution":
            final_status = "failed"

    summary = ""
    if result_event:
        summary = result_event.get("result", "")

    duration_ms = int((time.monotonic() - t0) * 1000)
    on_log({"type": "agent", "content": f"[finished in {duration_ms // 1000}s · status: {final_status}]"})

    return summary or instruction[:80], final_status
