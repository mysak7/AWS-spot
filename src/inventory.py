import json
from typing import Any

from config import HOSTS_FILE


class InventoryError(Exception):
    pass


def load_hosts() -> list[dict[str, Any]]:
    if not HOSTS_FILE.exists():
        return []
    try:
        with open(HOSTS_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError as e:
        raise InventoryError(f"hosts.json is corrupt: {e}") from e


def save_hosts(hosts: list[dict[str, Any]]) -> None:
    HOSTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HOSTS_FILE, "w") as f:
        json.dump(hosts, f, indent=2)


def add_host(host: dict[str, Any]) -> None:
    hosts = load_hosts()
    hosts.append(host)
    save_hosts(hosts)


def update_host(host_id: str, updates: dict[str, Any]) -> None:
    hosts = load_hosts()
    for host in hosts:
        if host["host_id"] == host_id:
            host.update(updates)
            save_hosts(hosts)
            return
    raise InventoryError(f"Host {host_id!r} not found in inventory")


def get_host(host_id: str) -> dict[str, Any] | None:
    for host in load_hosts():
        if host["host_id"] == host_id:
            return host
    return None


def list_hosts(status: str | None = None) -> list[dict[str, Any]]:
    hosts = load_hosts()
    if status:
        return [h for h in hosts if h.get("status") == status]
    return hosts
