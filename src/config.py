from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).parent.parent
CREDENTIALS_FILE = ROOT_DIR / "credentials.json"
HOSTS_FILE = ROOT_DIR / "hosts.json"
KEYS_DIR = ROOT_DIR / "keys"
DELETED_KEYS_DIR = ROOT_DIR / "keys" / "deleted"

# AWS
FREE_TIER_TYPES: set[str] = {"t2.micro", "t3.micro"}
SECURITY_GROUP_NAME = "spot-manager-sg"
SECURITY_GROUP_DESC = "Spot Manager — SSH only (TCP 22)"
SSH_USER = "ec2-user"
AMI_OWNER = "amazon"
AMI_NAME_FILTER = "al2023-ami-*-x86_64"
SPOT_HISTORY_HOURS = 1

DEFAULT_INSTANCE_TYPES: list[str] = [
    "t2.micro",
    "t3.micro",
    "t3.small",
    "t3.medium",
    "t3a.micro",
    "t3a.small",
    "t3a.medium",
    "c5.large",
    "c5.xlarge",
    "m5.large",
    "m5.xlarge",
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
