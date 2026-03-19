from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).parent.parent
CREDENTIALS_FILE = ROOT_DIR / "credentials.json"
HOSTS_FILE = ROOT_DIR / "hosts.json"
KEYS_DIR = ROOT_DIR / "keys"
DELETED_KEYS_DIR = ROOT_DIR / "keys" / "deleted"

# AWS
FREE_TIER_TYPES: set[str] = {"t3.micro", "t4g.micro"}
SECURITY_GROUP_NAME = "spot-manager-sg"
SECURITY_GROUP_DESC = "Spot Manager - SSH only (TCP 22)"
SSH_USER = "ec2-user"
AMI_OWNER = "amazon"
AMI_NAME_FILTER_X86 = "al2023-ami-*-x86_64"
AMI_NAME_FILTER_ARM = "al2023-ami-*-arm64"
# Keep legacy name pointing to x86 for any existing callers
AMI_NAME_FILTER = AMI_NAME_FILTER_X86
SPOT_HISTORY_HOURS = 1

# Instance types whose architecture is ARM (Graviton) — matched by prefix
ARM_INSTANCE_PREFIXES: tuple[str, ...] = ("t4g.", "c7g.", "m7g.", "r7g.", "c6g.", "m6g.", "r6g.")

DEFAULT_INSTANCE_TYPES: list[str] = [
    "t3.micro",       # 2 vCPU  1 GiB  x86 burstable
    "t3.small",       # 2 vCPU  2 GiB  x86 burstable
    "t4g.micro",      # 2 vCPU  1 GiB  ARM Graviton2
    "t4g.small",      # 2 vCPU  2 GiB  ARM Graviton2
    "c7i-flex.large", # 2 vCPU  4 GiB  Compute-optimized
    "m7i-flex.large", # 2 vCPU  8 GiB  General purpose
]

DEFAULT_REGIONS: list[str] = [
    "us-east-1",
    "us-east-2",
    "us-west-1",
    "us-west-2",
    "eu-west-1",
    "eu-west-2",
    "eu-west-3",
    "eu-central-1",
    "ap-southeast-1",
    "ap-southeast-2",
    "ap-northeast-1",
    "ap-south-1",
    "sa-east-1",
    "ca-central-1",
]
