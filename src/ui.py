from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from config import DEFAULT_INSTANCE_TYPES, DEFAULT_REGIONS, FREE_TIER_TYPES, NETBIRD_SETUP_KEY_DEFAULT

console = Console()


def print_banner(account_id: str) -> None:
    console.print(
        Panel(
            f"[bold cyan]AWS Spot Manager[/bold cyan]\n"
            f"Account: [yellow]{account_id}[/yellow]",
            box=box.DOUBLE_EDGE,
            expand=False,
        )
    )


def print_error(msg: str) -> None:
    console.print(f"[bold red]Error:[/bold red] {msg}")


def print_success(msg: str) -> None:
    console.print(f"[bold green]✓[/bold green] {msg}")


def print_warning(msg: str) -> None:
    console.print(f"[bold yellow]⚠[/bold yellow]  {msg}")


def main_menu() -> str:
    console.print()
    console.print("[bold]Main Menu[/bold]")
    options = [
        ("1", "Scan Spot Prices"),
        ("2", "View Inventory"),
        ("3", "Launch Instance"),
        ("4", "Connect to Host (show SSH command)"),
        ("5", "Terminate Host"),
        ("6", "Run Ansible Setup on Host"),
        ("7", "Settings"),
        ("8", "Exit"),
    ]
    for key, label in options:
        console.print(f"  [cyan]{key}[/cyan]  {label}")
    console.print()
    return Prompt.ask("Choose", choices=[k for k, _ in options], default="1")


def select_instance_types() -> list[str]:
    console.print("\n[bold]Instance Types[/bold]")
    for i, t in enumerate(DEFAULT_INSTANCE_TYPES, 1):
        ft = " [green](FT)[/green]" if t in FREE_TIER_TYPES else ""
        console.print(f"  [cyan]{i:2}[/cyan]  {t}{ft}")
    console.print(f"  [cyan] 0[/cyan]  All above")
    choice = Prompt.ask(
        "Select (comma-separated numbers, or 0 for all)", default="0"
    )
    if choice.strip() == "0":
        return DEFAULT_INSTANCE_TYPES[:]
    selected = []
    for part in choice.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(DEFAULT_INSTANCE_TYPES):
                selected.append(DEFAULT_INSTANCE_TYPES[idx])
    return selected or DEFAULT_INSTANCE_TYPES[:]


def select_regions() -> list[str]:
    console.print("\n[bold]Regions[/bold]")
    for i, r in enumerate(DEFAULT_REGIONS, 1):
        console.print(f"  [cyan]{i:2}[/cyan]  {r}")
    console.print(f"  [cyan] 0[/cyan]  All above")
    choice = Prompt.ask(
        "Select (comma-separated numbers, or 0 for all)", default="0"
    )
    if choice.strip() == "0":
        return DEFAULT_REGIONS[:]
    selected = []
    for part in choice.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(DEFAULT_REGIONS):
                selected.append(DEFAULT_REGIONS[idx])
    return selected or DEFAULT_REGIONS[:]


def show_spot_table(
    results: list[dict[str, Any]],
    catalog: dict[str, dict[str, Any]],
    limit: int = 30,
) -> None:
    table = Table(
        title=f"Spot Prices — top {min(len(results), limit)} cheapest",
        box=box.ROUNDED,
        show_lines=False,
        header_style="bold cyan",
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("Region", min_width=12)
    table.add_column("AZ", min_width=14)
    table.add_column("Instance Type", min_width=13)
    table.add_column("vCPU", justify="right")
    table.add_column("RAM GiB", justify="right")
    table.add_column("$/hr", justify="right", style="bold green")
    table.add_column("$/mo", justify="right", style="bold yellow")
    table.add_column("FT?", justify="center")

    for i, row in enumerate(results[:limit], 1):
        itype = row["instance_type"]
        info = catalog.get(itype, {})
        vcpu = str(info.get("vcpu", "?"))
        ram = str(info.get("memory_gib", "?"))
        ft = "[green]✓[/green]" if itype in FREE_TIER_TYPES else ""
        monthly = f"${float(row['spot_price_usd']) * 24 * 30:.2f}"
        table.add_row(
            str(i),
            row["region"],
            row["az"],
            itype,
            vcpu,
            ram,
            f"${row['spot_price_usd']}",
            monthly,
            ft,
        )

    console.print(table)


def select_spot_row(
    results: list[dict[str, Any]], limit: int = 30
) -> dict[str, Any] | None:
    count = min(len(results), limit)
    choice = Prompt.ask(
        f"Select row to launch (1-{count}, or 0 to cancel)", default="0"
    )
    if not choice.isdigit() or int(choice) == 0:
        return None
    idx = int(choice) - 1
    if 0 <= idx < count:
        return results[idx]
    return None


_STATUS_STYLE: dict[str, str] = {
    "running": "green",
    "terminated": "dim",
    "stopped": "yellow",
    "pending": "cyan",
    "shutting-down": "red",
}


def show_inventory(hosts: list[dict[str, Any]]) -> None:
    if not hosts:
        console.print("[dim]No hosts in inventory.[/dim]")
        return

    table = Table(
        title="Host Inventory",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("ID", min_width=12)
    table.add_column("Name", min_width=14)
    table.add_column("Region", min_width=11)
    table.add_column("Type", min_width=11)
    table.add_column("IP", min_width=14)
    table.add_column("$/hr", justify="right")
    table.add_column("$/mo", justify="right")
    table.add_column("Status", min_width=10)
    table.add_column("Launched", min_width=20)

    for i, h in enumerate(hosts, 1):
        status = h.get("status", "unknown")
        style = _STATUS_STYLE.get(status, "white")
        table.add_row(
            str(i),
            h.get("host_id", "?"),
            h.get("name", "?"),
            h.get("region", "?"),
            h.get("instance_type", "?"),
            h.get("public_ip", "?"),
            f"${h.get('spot_price_usd', '?')}",
            f"${h.get('monthly_price_usd', '?')}",
            f"[{style}]{status}[/{style}]",
            h.get("launched_at", "?"),
        )

    console.print(table)


def select_host(
    hosts: list[dict[str, Any]], status_filter: str | None = None
) -> dict[str, Any] | None:
    filtered = [
        h
        for h in hosts
        if status_filter is None or h.get("status") == status_filter
    ]
    if not filtered:
        label = f" with status '{status_filter}'" if status_filter else ""
        console.print(f"[dim]No hosts{label} in inventory.[/dim]")
        return None

    show_inventory(filtered)
    choice = Prompt.ask(
        f"Select host (1-{len(filtered)}, or 0 to cancel)", default="0"
    )
    if not choice.isdigit() or int(choice) == 0:
        return None
    idx = int(choice) - 1
    if 0 <= idx < len(filtered):
        return filtered[idx]
    return None


def show_host_detail(host: dict[str, Any]) -> None:
    lines = [f"[cyan]{k}:[/cyan] {v}" for k, v in host.items()]
    console.print(
        Panel(
            "\n".join(lines),
            title=f"[bold]{host.get('name', host.get('host_id'))}[/bold]",
            expand=False,
        )
    )


def confirm(msg: str, default: bool = False) -> bool:
    return Confirm.ask(msg, default=default)


def prompt_instance_name() -> str:
    return Prompt.ask("Instance name", default="")


def prompt_netbird_key(default: str = NETBIRD_SETUP_KEY_DEFAULT) -> str:
    return Prompt.ask("NetBird setup key", default=default)


def show_settings(settings: dict[str, Any]) -> dict[str, Any] | None:
    """Display current settings and return updated dict, or None if cancelled."""
    console.print()
    console.print(Panel(
        "\n".join(f"[cyan]{k}:[/cyan] {v}" for k, v in settings.items()),
        title="[bold]Settings[/bold]",
        expand=False,
    ))
    console.print()
    console.print("  [cyan]1[/cyan]  Edit NetBird setup key")
    console.print("  [cyan]0[/cyan]  Back")
    console.print()
    choice = Prompt.ask("Choose", choices=["0", "1"], default="0")
    if choice == "0":
        return None
    updated = dict(settings)
    if choice == "1":
        updated["netbird_setup_key"] = prompt_netbird_key(
            default=settings.get("netbird_setup_key", NETBIRD_SETUP_KEY_DEFAULT)
        )
    return updated


def prompt_ansible_output_mode() -> bool:
    """Return True if the user wants output in a new terminal window."""
    console.print("\n[bold]Ansible output[/bold]")
    console.print("  [cyan]1[/cyan]  Inline (stream to this terminal)")
    console.print("  [cyan]2[/cyan]  New window (open terminal emulator)")
    console.print()
    choice = Prompt.ask("Choose", choices=["1", "2"], default="1")
    return choice == "2"
