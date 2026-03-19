from datetime import datetime, timezone, timedelta
from typing import Any

from botocore.exceptions import ClientError

from config import DEFAULT_REGIONS, SPOT_HISTORY_HOURS
from credentials import get_client


class SpotScanError(Exception):
    pass


def get_enabled_regions(creds: dict[str, str]) -> list[str]:
    """Return all regions enabled for this account."""
    client = get_client("ec2", creds["aws_region"], creds)
    try:
        resp = client.describe_regions(
            Filters=[
                {
                    "Name": "opt-in-status",
                    "Values": ["opt-in-not-required", "opted-in"],
                }
            ]
        )
        return [r["RegionName"] for r in resp["Regions"]]
    except ClientError as e:
        raise SpotScanError(
            f"Failed to list regions: {e.response['Error']['Message']}"
        ) from e


def scan_spot_prices(
    instance_types: list[str],
    creds: dict[str, str],
    regions: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Scan spot prices across regions for the given instance types.
    Returns list of dicts sorted by price ascending.
    """
    if regions is None:
        regions = DEFAULT_REGIONS

    start_time = datetime.now(timezone.utc) - timedelta(hours=SPOT_HISTORY_HOURS)
    results: list[dict[str, Any]] = []

    for region in regions:
        client = get_client("ec2", region, creds)
        # Track latest price per (instance_type, az) pair
        latest: dict[tuple[str, str], dict[str, Any]] = {}

        try:
            paginator = client.get_paginator("describe_spot_price_history")
            pages = paginator.paginate(
                InstanceTypes=instance_types,
                ProductDescriptions=["Linux/UNIX"],
                StartTime=start_time,
            )
            for page in pages:
                for entry in page["SpotPriceHistory"]:
                    key = (entry["InstanceType"], entry["AvailabilityZone"])
                    if key not in latest or entry["Timestamp"] > latest[key]["timestamp"]:
                        latest[key] = {
                            "region": region,
                            "az": entry["AvailabilityZone"],
                            "instance_type": entry["InstanceType"],
                            "spot_price_usd": entry["SpotPrice"],
                            "timestamp": entry["Timestamp"],
                        }
        except ClientError:
            # Skip regions we can't access (not opted in, permission denied, etc.)
            continue

        results.extend(latest.values())

    results.sort(key=lambda x: float(x["spot_price_usd"]))
    return results
