import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

from config import (
    AMI_NAME_FILTER_ARM,
    AMI_NAME_FILTER_X86,
    AMI_OWNER,
    ARM_INSTANCE_PREFIXES,
    DELETED_KEYS_DIR,
    FREE_TIER_TYPES,
    KEYS_DIR,
    SECURITY_GROUP_DESC,
    SECURITY_GROUP_NAME,
    SSH_USER,
)
from credentials import get_client
from inventory import add_host, update_host


class ProvisionError(Exception):
    pass


def _is_arm(instance_type: str) -> bool:
    return instance_type.startswith(ARM_INSTANCE_PREFIXES)


def get_latest_ami(client: Any, instance_type: str = "") -> str:
    """Fetch the latest Amazon Linux 2023 AMI for the given instance type's architecture."""
    arm = _is_arm(instance_type)
    name_filter = AMI_NAME_FILTER_ARM if arm else AMI_NAME_FILTER_X86
    arch = "arm64" if arm else "x86_64"
    try:
        resp = client.describe_images(
            Owners=[AMI_OWNER],
            Filters=[
                {"Name": "name", "Values": [name_filter]},
                {"Name": "state", "Values": ["available"]},
                {"Name": "architecture", "Values": [arch]},
            ],
        )
    except ClientError as e:
        raise ProvisionError(
            f"Failed to fetch AMI: {e.response['Error']['Message']}"
        ) from e

    images = resp.get("Images", [])
    if not images:
        raise ProvisionError(f"No Amazon Linux 2023 {arch} AMI found in this region")

    images.sort(key=lambda x: x["CreationDate"], reverse=True)
    return images[0]["ImageId"]


def get_default_subnet(client: Any, az: str) -> str:
    """Return the default subnet ID for the given AZ."""
    try:
        resp = client.describe_subnets(
            Filters=[
                {"Name": "availabilityZone", "Values": [az]},
                {"Name": "defaultForAz", "Values": ["true"]},
            ]
        )
        subnets = resp.get("Subnets", [])
        if not subnets:
            raise ProvisionError(f"No default subnet found in {az}")
        return subnets[0]["SubnetId"]
    except ClientError as e:
        raise ProvisionError(
            f"Failed to find subnet in {az}: {e.response['Error']['Message']}"
        ) from e


def ensure_security_group(client: Any) -> str:
    """Return group ID of existing spot-manager-sg, or create it (SSH only)."""
    try:
        resp = client.describe_security_groups(
            Filters=[{"Name": "group-name", "Values": [SECURITY_GROUP_NAME]}]
        )
        groups = resp.get("SecurityGroups", [])
        if groups:
            return groups[0]["GroupId"]
    except ClientError as e:
        raise ProvisionError(
            f"Failed to query security groups: {e.response['Error']['Message']}"
        ) from e

    try:
        resp = client.create_security_group(
            GroupName=SECURITY_GROUP_NAME,
            Description=SECURITY_GROUP_DESC,
        )
        sg_id = resp["GroupId"]
        client.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": 22,
                    "ToPort": 22,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "SSH"}],
                }
            ],
        )
        return sg_id
    except ClientError as e:
        raise ProvisionError(
            f"Failed to create security group: {e.response['Error']['Message']}"
        ) from e


def _write_key_file(key_name: str, key_material: str) -> Path:
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    DELETED_KEYS_DIR.mkdir(parents=True, exist_ok=True)
    key_path = KEYS_DIR / f"{key_name}.pem"
    key_path.write_text(key_material)
    key_path.chmod(0o400)
    return key_path


def provision_instance(
    region: str,
    az: str,
    instance_type: str,
    spot_price_usd: str,
    creds: dict[str, str],
    progress_cb: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Full provisioning flow: key pair → security group → AMI → spot request → wait.
    Saves host to inventory and returns the host record.
    """
    def _p(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)

    client = get_client("ec2", region, creds)
    key_name = f"spot-{uuid.uuid4()}"

    _p("Creating key pair...")
    try:
        kp_resp = client.create_key_pair(KeyName=key_name)
    except ClientError as e:
        raise ProvisionError(
            f"Failed to create key pair: {e.response['Error']['Message']}"
        ) from e

    key_path = _write_key_file(key_name, kp_resp["KeyMaterial"])

    try:
        _p("Ensuring security group...")
        sg_id = ensure_security_group(client)
        _p("Fetching latest AMI and default subnet...")
        ami_id = get_latest_ami(client, instance_type)
        subnet_id = get_default_subnet(client, az)

        # Bid 2x current price for higher fill probability
        bid = f"{float(spot_price_usd) * 2:.6f}"

        _p("Submitting spot request...")
        try:
            run_resp = client.run_instances(
                ImageId=ami_id,
                InstanceType=instance_type,
                KeyName=key_name,
                MinCount=1,
                MaxCount=1,
                InstanceMarketOptions={
                    "MarketType": "spot",
                    "SpotOptions": {
                        "MaxPrice": bid,
                        "SpotInstanceType": "one-time",
                    },
                },
                NetworkInterfaces=[
                    {
                        "DeviceIndex": 0,
                        "SubnetId": subnet_id,
                        "Groups": [sg_id],
                        "AssociatePublicIpAddress": True,
                    }
                ],
                Placement={"AvailabilityZone": az},
            )
        except ClientError as e:
            raise ProvisionError(
                f"Spot request failed: {e.response['Error']['Message']}"
            ) from e

        instance_id = run_resp["Instances"][0]["InstanceId"]
        _p("Waiting for instance to reach running state...")
        public_ip = _wait_for_running(client, instance_id)
        _p("Saving to inventory...")

        rel_key = f"keys/{key_name}.pem"
        abs_key = str(KEYS_DIR / f"{key_name}.pem")
        ssh_cmd = f"ssh -i {abs_key} {SSH_USER}@{public_ip}"

        host: dict[str, Any] = {
            "host_id": instance_id,
            "name": f"spot-{instance_id[-6:]}",
            "region": region,
            "az": az,
            "instance_type": instance_type,
            "public_ip": public_ip,
            "key_file": rel_key,
            "key_name": key_name,
            "ssh_cmd": ssh_cmd,
            "launched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "spot_price_usd": spot_price_usd,
            "monthly_price_usd": f"{float(spot_price_usd) * 24 * 30:.2f}",
            "status": "running",
        }
        add_host(host)
        return host

    except Exception:
        # Clean up key file and AWS key pair on any failure
        key_path.unlink(missing_ok=True)
        try:
            client.delete_key_pair(KeyName=key_name)
        except ClientError:
            pass
        raise



def _wait_for_running(client: Any, instance_id: str, timeout: int = 180) -> str:
    """Poll until instance is running. Returns public IP."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = client.describe_instances(InstanceIds=[instance_id])
            inst = resp["Reservations"][0]["Instances"][0]
            state = inst["State"]["Name"]
            if state == "running" and inst.get("PublicIpAddress"):
                return inst["PublicIpAddress"]
            if state in ("terminated", "shutting-down"):
                raise ProvisionError(f"Instance {instance_id} entered state: {state}")
        except ClientError as e:
            raise ProvisionError(
                f"Error polling instance: {e.response['Error']['Message']}"
            ) from e
        time.sleep(5)
    raise ProvisionError(f"Instance not running within {timeout}s")


def terminate_host(host: dict[str, Any], creds: dict[str, str]) -> None:
    """Terminate instance, archive key file, delete AWS key pair, update inventory."""
    client = get_client("ec2", host["region"], creds)

    try:
        client.terminate_instances(InstanceIds=[host["host_id"]])
    except ClientError as e:
        raise ProvisionError(
            f"Terminate failed: {e.response['Error']['Message']}"
        ) from e

    # Archive key file
    key_path = Path(host["key_file"])
    if key_path.exists():
        DELETED_KEYS_DIR.mkdir(parents=True, exist_ok=True)
        key_path.rename(DELETED_KEYS_DIR / key_path.name)

    # Delete key pair from AWS
    key_name = host.get("key_name")
    if key_name:
        try:
            client.delete_key_pair(KeyName=key_name)
        except ClientError:
            pass

    update_host(host["host_id"], {"status": "terminated"})


def reconcile_inventory(
    hosts: list[dict[str, Any]], creds: dict[str, str]
) -> int:
    """
    Check live AWS state for all non-terminated hosts.
    Updates status in inventory. Returns count of updated records.
    """
    active = [h for h in hosts if h.get("status") != "terminated"]
    if not active:
        return 0

    # Group by region to minimise API calls
    by_region: dict[str, list[dict[str, Any]]] = {}
    for h in active:
        by_region.setdefault(h["region"], []).append(h)

    updated = 0
    for region, region_hosts in by_region.items():
        client = get_client("ec2", region, creds)
        ids = [h["host_id"] for h in region_hosts]
        try:
            resp = client.describe_instances(InstanceIds=ids)
        except ClientError:
            continue

        live: dict[str, str] = {}
        for reservation in resp["Reservations"]:
            for inst in reservation["Instances"]:
                live[inst["InstanceId"]] = inst["State"]["Name"]

        for host in region_hosts:
            live_state = live.get(host["host_id"], "terminated")
            if live_state != host.get("status"):
                update_host(host["host_id"], {"status": live_state})
                updated += 1

    return updated
