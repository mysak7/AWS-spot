import json
import re
import time
from collections.abc import Callable
from typing import Any

from openai import OpenAI

from .ssh_client import SSHClient
from llm_log import append_query

MAX_STEPS = 40

SYSTEM_PROMPT = """\
You control a remote EC2 spot instance via SSH. You do NOT have direct access to any \
local machine or filesystem. Every command you want to run must be sent as a JSON object \
so the system can SSH it to the remote server and return the output to you.

YOU MUST reply with ONLY a raw JSON object — no markdown, no backticks, no explanation, \
no prose before or after. Just the JSON.

To run a command on the remote server:
{"action": "run", "command": "the shell command"}

When the task is fully complete:
{"action": "done", "message": "brief description of what was done"}

Rules:
- One command per reply
- Wait for the output before deciding the next command
- Use sudo when needed
- If a command fails, fix it before moving on
- Do not describe what you are doing — just output the JSON
"""


def _parse_action(text: str) -> dict | None:
    """Extract the first JSON object from the model response."""
    text = text.strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Find JSON block inside backticks or anywhere in the text
    match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _call(client: OpenAI, messages: list, host_id: str, session_id: str, step: int) -> Any:
    t0 = time.monotonic()
    resp = client.chat.completions.create(
        model="claude-code",
        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
    )
    duration_ms = int((time.monotonic() - t0) * 1000)
    usage = resp.usage
    if usage:
        append_query(
            host_id=host_id,
            session_id=session_id,
            step=step,
            model=resp.model or "claude-code",
            input_tokens=usage.prompt_tokens or 0,
            output_tokens=usage.completion_tokens or 0,
            duration_ms=duration_ms,
        )
    return resp


def run_agent(
    host: dict[str, Any],
    instruction: str,
    on_log: Callable[[dict[str, Any]], None],
    bridge_url: str = "http://localhost:8001",
    bridge_api_key: str = "test",
    session_id: str = "",
) -> str:
    """
    Connect via SSH, let Claude (via ClaudeBridge) run commands to fulfill the instruction.
    Streams log entries via on_log callback.
    Returns a summary string.
    """
    host_id = host.get("host_id", "unknown")
    client = OpenAI(base_url=f"{bridge_url.rstrip('/')}/v1", api_key=bridge_api_key)
    ssh = SSHClient(hostname=host["public_ip"], key_filename=host["key_file"])

    messages: list[dict[str, Any]] = [{"role": "user", "content": instruction}]
    steps = 0
    parse_failures = 0
    last_message = ""

    try:
        while steps < MAX_STEPS:
            response = _call(client, messages, host_id, session_id, steps + 1)

            raw = response.choices[0].message.content or ""
            action = _parse_action(raw)

            if action is None:
                parse_failures += 1
                on_log({"type": "agent", "content": f"[raw] {raw.strip()}"})
                if parse_failures >= 2:
                    last_message = raw.strip()
                    break
                # Ask Claude to retry with proper JSON
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": 'Reply with ONLY a JSON object. Example: {"action": "run", "command": "uname -a"}',
                })
                continue

            parse_failures = 0

            if action.get("action") == "done":
                last_message = action.get("message", "Done.")
                on_log({"type": "agent", "content": last_message})
                break

            if action.get("action") == "run":
                command = action.get("command", "")
                on_log({"type": "cmd", "content": command})

                out, err, exit_code = ssh.run(command)

                output_parts = []
                if out.strip():
                    output_parts.append(out.rstrip())
                if err.strip():
                    output_parts.append(f"[stderr]\n{err.rstrip()}")
                if exit_code != 0:
                    output_parts.append(f"[exit code: {exit_code}]")
                output = "\n".join(output_parts) or "(no output)"

                on_log({"type": "output", "content": output})

                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": f"Command output:\n{output}\n\nContinue with the next step.",
                })
                steps += 1
            else:
                on_log({"type": "agent", "content": raw.strip()})
                last_message = raw.strip()
                break

        # Generate summary
        t0 = time.monotonic()
        summary_resp = client.chat.completions.create(
            model="claude-code",
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Original instruction: {instruction}\n\n"
                        f"Final status: {last_message}\n\n"
                        "Write a 1-3 sentence summary of what was accomplished. "
                        "Plain text only, no JSON."
                    ),
                }
            ],
        )
        dur = int((time.monotonic() - t0) * 1000)
        usage = summary_resp.usage
        if usage:
            append_query(
                host_id=host_id,
                session_id=session_id,
                step=0,
                model=summary_resp.model or "claude-code",
                input_tokens=usage.prompt_tokens or 0,
                output_tokens=usage.completion_tokens or 0,
                duration_ms=dur,
            )
        return summary_resp.choices[0].message.content.strip()

    finally:
        ssh.close()
