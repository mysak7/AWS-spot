import paramiko


class SSHClient:
    def __init__(
        self,
        hostname: str,
        key_filename: str,
        username: str = "ec2-user",
        connect_timeout: int = 30,
    ) -> None:
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._client.connect(
            hostname=hostname,
            username=username,
            key_filename=str(key_filename),
            timeout=connect_timeout,
            look_for_keys=False,
            allow_agent=False,
        )

    def run(self, command: str, timeout: int = 120) -> tuple[str, str, int]:
        """Run command, return (stdout, stderr, exit_code)."""
        _, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        return out, err, code

    def close(self) -> None:
        self._client.close()
