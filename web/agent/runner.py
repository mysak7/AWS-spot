import json
import re
from collections.abc import Callable
from typing import Any

from openai import OpenAI

from .ssh_client import SSHClient

MAX_STEPS = 40

SYSTEM_PROMPT = """\
You are a Linux system administration agent with SSH access to a remote EC2 instance \
running Amazon Linux 2023. You are logged in as ec2-user with full sudo access.

Execute the user's instructions step by step. After each step, decide what to do next.

IMPORTANT: Always respond with ONLY a single JSON object — no other text before or after it.

To run a shell command:
{"action": "run", "command": "<shell command>"}

When fully done:
{"action": "done", "message": "<short completion message>"}

Rules:
- One command at a time; wait for output before deciding next step
- Use sudo when needed
- If a command fails, diagnose and fix before moving on
- Be efficient — avoid unnecessary commands
- When all instructions are complete, respond with the "done" action
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


def run_agent(
    host: dict[str, Any],
    instruction: str,
    on_log: Callable[[dict[str, Any]], None],
    bridge_url: str = "http://localhost:8001",
    bridge_api_key: str = "test",
) -> str:
    """
    Connect via SSH, let Claude (via ClaudeBridge) run commands to fulfill the instruction.
    Streams log entries via on_log callback.
    Returns a summary string.
    """
    client = OpenAI(base_url=f"{bridge_url.rstrip('/')}/v1", api_key=bridge_api_key)
    ssh = SSHClient(hostname=host["public_ip"], key_filename=host["key_file"])

    messages: list[dict[str, Any]] = [{"role": "user", "content": instruction}]
    steps = 0
    last_message = ""

    try:
        while steps < MAX_STEPS:
            response = client.chat.completions.create(
                model="claude-code",
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            )

            raw = response.choices[0].message.content or ""
            action = _parse_action(raw)

            if action is None:
                # Unparseable — log as agent text and stop
                on_log({"type": "agent", "content": raw.strip()})
                last_message = raw.strip()
                break

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

                # Append assistant turn + tool result as user message
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": f"Command output:\n{output}\n\nContinue with the next step.",
                })
                steps += 1
            else:
                # Unknown action — log and stop
                on_log({"type": "agent", "content": raw.strip()})
                last_message = raw.strip()
                break

        # Generate summary
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
        return summary_resp.choices[0].message.content.strip()

    finally:
        ssh.close()
