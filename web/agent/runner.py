import os
from collections.abc import Callable
from typing import Any

import anthropic

from .ssh_client import SSHClient

MAX_TOOL_CALLS = 40

SYSTEM_PROMPT = """\
You are a Linux system administration agent with SSH access to a remote EC2 instance \
running Amazon Linux 2023. You are logged in as ec2-user with full sudo access.

Execute the user's instructions by calling the run_command tool. Rules:
- Run one command at a time; check output before continuing
- Use sudo when needed
- If a command fails, diagnose and fix it before moving on
- Be efficient — avoid unnecessary commands
- When fully done, stop calling tools and write a short completion message
"""

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "run_command",
        "description": "Execute a shell command on the remote server and return its output.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute",
                }
            },
            "required": ["command"],
        },
    }
]


def run_agent(
    host: dict[str, Any],
    instruction: str,
    on_log: Callable[[dict[str, Any]], None],
) -> str:
    """
    Connect via SSH, let Claude run commands to fulfill the instruction.
    Streams log entries via on_log callback.
    Returns a summary string.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to your .env file or environment."
        )

    client = anthropic.Anthropic(api_key=api_key)
    ssh = SSHClient(hostname=host["public_ip"], key_filename=host["key_file"])

    messages: list[dict[str, Any]] = [{"role": "user", "content": instruction}]
    tool_calls = 0

    try:
        while tool_calls < MAX_TOOL_CALLS:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=_TOOLS,
                messages=messages,
            )

            # Log agent text blocks
            for block in response.content:
                if hasattr(block, "text") and block.text.strip():
                    on_log({"type": "agent", "content": block.text.strip()})

            if response.stop_reason == "end_turn":
                break

            if response.stop_reason != "tool_use":
                break

            # Execute tool calls
            tool_results = []
            for block in response.content:
                if not (hasattr(block, "type") and block.type == "tool_use"):
                    continue
                if block.name != "run_command":
                    continue

                command = block.input.get("command", "")
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
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })
                tool_calls += 1

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        # Generate summary from conversation history
        summary_resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system="Summarize completed technical tasks concisely.",
            messages=[
                *messages[-8:],  # last few turns for context
                {
                    "role": "user",
                    "content": (
                        f"Original instruction: {instruction}\n\n"
                        "Write a 1-3 sentence summary of what was accomplished."
                    ),
                },
            ],
        )
        return summary_resp.content[0].text.strip()

    finally:
        ssh.close()
