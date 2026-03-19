import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from config import ANSIBLE_PLAYBOOK, SSH_USER


class AnsibleError(Exception):
    pass


def _find_terminal() -> str | None:
    for term in ("xterm", "gnome-terminal", "xfce4-terminal", "konsole", "lxterminal", "mate-terminal"):
        if shutil.which(term):
            return term
    return None


def _build_inventory(host: dict[str, Any]) -> str:
    ip = host["public_ip"]
    key_file = host["key_file"]
    return (
        f"[all]\n"
        f"{ip} ansible_user={SSH_USER} "
        f"ansible_ssh_private_key_file={key_file} "
        f"ansible_ssh_common_args='-o StrictHostKeyChecking=no'\n"
    )


def run_ansible_setup(host: dict[str, Any], netbird_key: str, new_window: bool) -> None:
    """Run ansible/setup.yml against *host*.

    If *new_window* is True the playbook is launched in a new terminal emulator
    window (stdout/stderr visible there).  Otherwise it runs inline, inheriting
    the current terminal so rich output streams to the console.
    """
    if not shutil.which("ansible-playbook"):
        raise AnsibleError(
            "ansible-playbook not found in PATH. "
            "Install Ansible: pip install ansible  or  apt install ansible"
        )

    if not ANSIBLE_PLAYBOOK.exists():
        raise AnsibleError(f"Playbook not found: {ANSIBLE_PLAYBOOK}")

    inv_fd, inv_path = tempfile.mkstemp(suffix=".ini", prefix="spot-inv-")
    try:
        with os.fdopen(inv_fd, "w") as f:
            f.write(_build_inventory(host))

        playbook = str(ANSIBLE_PLAYBOOK)
        netbird_arg = f"netbird_setup_key={netbird_key}"

        if new_window:
            term = _find_terminal()
            if term is None:
                raise AnsibleError(
                    "No terminal emulator found (tried xterm, gnome-terminal, etc.). "
                    "Run inline instead."
                )

            # Build the shell command that runs ansible and waits before closing
            shell_cmd = (
                f"ansible-playbook {shlex.quote(playbook)} "
                f"-i {shlex.quote(inv_path)} "
                f"-e {shlex.quote(netbird_arg)}; "
                f"rm -f {shlex.quote(inv_path)}; "
                f"echo; echo '--- Finished. Press Enter to close ---'; read _"
            )

            if term == "gnome-terminal":
                subprocess.Popen([term, "--", "bash", "-c", shell_cmd])
            else:
                subprocess.Popen([term, "-e", f"bash -c {shlex.quote(shell_cmd)}"])
            # inv_path will be deleted by the shell command inside the new window
        else:
            try:
                subprocess.run(
                    ["ansible-playbook", playbook, "-i", inv_path, "-e", netbird_arg],
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                raise AnsibleError(f"ansible-playbook exited with code {e.returncode}")
            finally:
                Path(inv_path).unlink(missing_ok=True)

    except Exception:
        # Clean up inv file if new_window path was not reached
        if Path(inv_path).exists():
            Path(inv_path).unlink(missing_ok=True)
        raise
