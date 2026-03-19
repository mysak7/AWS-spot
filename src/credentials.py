import json
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from config import CREDENTIALS_FILE


class CredentialsError(Exception):
    pass


def load_credentials() -> dict[str, str]:
    """Load and basic-validate credentials.json."""
    if not CREDENTIALS_FILE.exists():
        raise CredentialsError(
            f"credentials.json not found at {CREDENTIALS_FILE}\n"
            "Create it with keys: aws_access_key_id, aws_secret_access_key, aws_region"
        )
    try:
        with open(CREDENTIALS_FILE) as f:
            creds: dict[str, str] = json.load(f)
    except json.JSONDecodeError as e:
        raise CredentialsError(f"credentials.json is not valid JSON: {e}") from e

    required = {"aws_access_key_id", "aws_secret_access_key", "aws_region"}
    missing = required - creds.keys()
    if missing:
        raise CredentialsError(
            f"credentials.json missing keys: {', '.join(sorted(missing))}"
        )
    return creds


def validate_credentials(creds: dict[str, str]) -> str:
    """Validate credentials via STS. Returns AWS account ID."""
    try:
        client = _make_client("sts", creds["aws_region"], creds)
        identity = client.get_caller_identity()
        return identity["Account"]
    except ClientError as e:
        raise CredentialsError(
            f"AWS credentials invalid: {e.response['Error']['Message']}"
        ) from e
    except BotoCoreError as e:
        raise CredentialsError(f"AWS connection error: {e}") from e


def get_client(service: str, region: str, creds: dict[str, str]) -> Any:
    """Factory: create a boto3 client for the given service and region."""
    return _make_client(service, region, creds)


def _make_client(service: str, region: str, creds: dict[str, str]) -> Any:
    return boto3.client(
        service,
        region_name=region,
        aws_access_key_id=creds["aws_access_key_id"],
        aws_secret_access_key=creds["aws_secret_access_key"],
    )
