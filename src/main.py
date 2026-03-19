import sys
from pathlib import Path

# Ensure src/ is importable when invoked as `python src/main.py` from repo root
sys.path.insert(0, str(Path(__file__).parent))

from rich.progress import Progress, SpinnerColumn, TextColumn

import ui
from config import FREE_TIER_TYPES
from credentials import CredentialsError, load_credentials, validate_credentials
from instance_catalog import InstanceCatalogError, get_instance_info
from inventory import load_hosts
from provisioner import ProvisionError, provision_instance, reconcile_inventory, terminate_host
from spot_scanner import SpotScanError, scan_spot_prices


def _run_scan(creds: dict) -> tuple[list[dict], dict] | None:
    """Shared scan flow used by both Scan and Launch actions."""
    instance_types = ui.select_instance_types()
    regions = ui.select_regions()

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        task = progress.add_task("Scanning spot prices across regions...", total=None)
        try:
            results = scan_spot_prices(instance_types, creds, regions)
        except SpotScanError as e:
            ui.print_error(str(e))
            return None

        progress.update(task, description="Fetching instance specs...")
        found_types = list({r["instance_type"] for r in results})
        try:
            catalog = (
                get_instance_info(found_types, creds, creds["aws_region"])
                if found_types
                else {}
            )
        except InstanceCatalogError as e:
            ui.print_error(str(e))
            catalog = {}

    if not results:
        ui.console.print("[dim]No spot prices found for the selected filters.[/dim]")
        return None

    ui.show_spot_table(results, catalog)
    return results, catalog


def action_scan(creds: dict) -> None:
    _run_scan(creds)


def action_inventory(_creds: dict) -> None:
    hosts = load_hosts()
    ui.show_inventory(hosts)


def action_launch(creds: dict) -> None:
    result = _run_scan(creds)
    if result is None:
        return
    results, _catalog = result

    selected = ui.select_spot_row(results)
    if selected is None:
        return

    itype = selected["instance_type"]

    if itype not in FREE_TIER_TYPES:
        ui.print_warning(
            f"{itype} is NOT Free Tier eligible — you will be charged "
            f"~${selected['spot_price_usd']}/hr."
        )
    ui.print_warning(
        "Spot Instances can be interrupted by AWS with 2 minutes notice."
    )

    if not ui.confirm(
        f"Launch {itype} in {selected['az']} at ${selected['spot_price_usd']}/hr?",
        default=False,
    ):
        return

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task(
            "Provisioning instance — this may take 1-2 minutes...", total=None
        )
        try:
            host = provision_instance(
                region=selected["region"],
                az=selected["az"],
                instance_type=itype,
                spot_price_usd=selected["spot_price_usd"],
                creds=creds,
            )
        except ProvisionError as e:
            ui.print_error(str(e))
            return

    ui.print_success(f"Instance launched: {host['host_id']}")
    ui.show_host_detail(host)
    ui.console.print(f"\n[bold]SSH:[/bold] [cyan]{host['ssh_cmd']}[/cyan]")


def action_connect(_creds: dict) -> None:
    hosts = load_hosts()
    host = ui.select_host(hosts, status_filter="running")
    if host:
        ui.console.print(
            f"\n[bold]SSH command:[/bold]\n  [cyan]{host['ssh_cmd']}[/cyan]\n"
        )


def action_terminate(creds: dict) -> None:
    hosts = load_hosts()
    host = ui.select_host(hosts, status_filter="running")
    if host is None:
        return

    ui.show_host_detail(host)
    if not ui.confirm(
        f"Terminate {host['host_id']}? This cannot be undone.", default=False
    ):
        return

    try:
        terminate_host(host, creds)
        ui.print_success(f"Host {host['host_id']} terminated.")
    except ProvisionError as e:
        ui.print_error(str(e))


_ACTIONS = {
    "1": action_scan,
    "2": action_inventory,
    "3": action_launch,
    "4": action_connect,
    "5": action_terminate,
}


def main() -> None:
    # Load credentials
    try:
        creds = load_credentials()
    except CredentialsError as e:
        ui.print_error(str(e))
        sys.exit(1)

    # Validate with AWS
    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task("Validating AWS credentials...", total=None)
        try:
            account_id = validate_credentials(creds)
        except CredentialsError as e:
            ui.print_error(str(e))
            sys.exit(1)

    ui.print_banner(account_id)

    # Reconcile inventory on startup
    hosts = load_hosts()
    if hosts:
        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            progress.add_task("Reconciling inventory with live AWS state...", total=None)
            try:
                updated = reconcile_inventory(hosts, creds)
                if updated:
                    ui.print_success(f"Reconciled {updated} host status(es).")
            except Exception:
                pass  # Non-fatal — proceed with cached state

    # Main loop
    while True:
        choice = ui.main_menu()
        if choice == "6":
            ui.console.print("[dim]Goodbye.[/dim]")
            break
        action = _ACTIONS.get(choice)
        if action:
            try:
                action(creds)
            except KeyboardInterrupt:
                ui.console.print("\n[dim]Cancelled.[/dim]")
            except Exception as e:
                ui.print_error(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
