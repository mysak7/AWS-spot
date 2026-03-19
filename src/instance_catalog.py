from typing import Any

from botocore.exceptions import ClientError

from credentials import get_client


class InstanceCatalogError(Exception):
    pass


def get_instance_info(
    instance_types: list[str],
    creds: dict[str, str],
    region: str,
) -> dict[str, dict[str, Any]]:
    """Return vCPU and memory info keyed by instance type."""
    client = get_client("ec2", region, creds)
    result: dict[str, dict[str, Any]] = {}

    # API accepts max 100 types per call
    for chunk in _chunks(instance_types, 100):
        try:
            resp = client.describe_instance_types(InstanceTypes=chunk)
        except ClientError as e:
            raise InstanceCatalogError(
                f"Failed to fetch instance types: {e.response['Error']['Message']}"
            ) from e
        for item in resp["InstanceTypes"]:
            itype = item["InstanceType"]
            result[itype] = {
                "vcpu": item["VCpuInfo"]["DefaultVCpus"],
                "memory_gib": round(item["MemoryInfo"]["SizeInMiB"] / 1024, 1),
            }

    return result


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]
