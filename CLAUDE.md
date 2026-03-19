# CLAUDE.md — AWS Spot Manager

## Project Purpose
CLI tool to find cheap AWS Spot Instance prices across regions, provision EC2 hosts with SSH access, and manage a local inventory of created/terminated hosts.

## Architecture Overview
```
aws-spot-manager/
├── credentials.json          # AWS credentials (never commit)
├── hosts.json                # Persistent host inventory
├── keys/                     # SSH .pem files (chmod 400)
│   └── deleted/              # Archived keys of terminated hosts
├── src/
│   ├── main.py               # Entry point, menu loop
│   ├── credentials.py        # Load & validate credentials.json
│   ├── spot_scanner.py       # Query describe_spot_price_history across regions
│   ├── instance_catalog.py   # Fetch vCPU/RAM via describe_instance_types
│   ├── provisioner.py        # Key pair, SG, spot request, SSH output
│   ├── inventory.py          # hosts.json CRUD helpers
│   └── ui.py                 # rich tables, menus, prompts
├── requirements.txt
└── README.md
```

## Tech Stack
- Python 3.11+
- `boto3` for all AWS API calls
- `rich` for all terminal output (tables, prompts, panels)
- `python-dotenv` for reading credentials.json / .env
- No external paid APIs or services

## Commands
```bash
# Install dependencies
pip install -r requirements.txt

# Run the tool
python src/main.py

# Run tests
pytest tests/ -v

# Lint
ruff check src/
```

## Coding Standards
- Type hints on all function signatures
- Each module has a single responsibility matching its filename
- No hardcoded AWS values (region, AMI IDs, instance types) — use constants in `src/config.py`
- All boto3 clients are created via a factory in `credentials.py`, never inline
- Use `rich.console.Console()` for all output — no bare `print()` calls
- Errors raise typed exceptions (e.g. `CredentialsError`, `SpotScanError`); caught and displayed in `main.py`
- All file I/O for `hosts.json` goes through `inventory.py` only

## Key Business Rules
1. Credentials loaded exclusively from `credentials.json` at project root — never from env vars or hardcoded
2. Always warn the user before launching any instance that is NOT `t2.micro` / `t3.micro` (Free Tier boundary)
3. Spot interruption warning must appear before every `request_spot_instances` call
4. Key pair names use format `spot-<uuid4>` to avoid collisions
5. `hosts.json` records are never deleted — terminated hosts get `"status": "terminated"`
6. On startup, reconcile `hosts.json` against live AWS state and update stale statuses
7. Security group `spot-manager-sg` is reused if it already exists in the target region

## hosts.json Schema
```json
{
  "host_id": "i-0abc123",
  "name": "spot-host-01",
  "region": "us-east-1",
  "az": "us-east-1b",
  "instance_type": "t3.micro",
  "public_ip": "54.x.x.x",
  "key_file": "keys/i-0abc123.pem",
  "ssh_cmd": "ssh -i keys/i-0abc123.pem ec2-user@54.x.x.x",
  "launched_at": "2026-03-19T10:00:00Z",
  "spot_price_usd": "0.0031",
  "status": "running"
}
```

## AWS APIs Used
| Call | Module |
|---|---|
| `sts.get_caller_identity` | credentials.py |
| `ec2.describe_regions` | spot_scanner.py |
| `ec2.describe_spot_price_history` | spot_scanner.py |
| `ec2.describe_instance_types` | instance_catalog.py |
| `ec2.create_key_pair` | provisioner.py |
| `ec2.create_security_group` | provisioner.py |
| `ec2.request_spot_instances` | provisioner.py |
| `ec2.describe_instances` | provisioner.py |
| `ec2.terminate_instances` | provisioner.py |
| `ec2.delete_key_pair` | provisioner.py |

## Terminology
- **Spot Price** — current hourly price for a Spot Instance in a given AZ
- **FT-eligible** — instance type qualifies for AWS Free Tier (t2.micro / t3.micro only)
- **Host** — a provisioned EC2 Spot Instance tracked in hosts.json
- **Inventory** — the full content of hosts.json
- **AZ** — Availability Zone (e.g. us-east-1b); prices differ per AZ within the same region

## Security Rules
- `credentials.json` and `keys/` are in `.gitignore` — never commit them
- `.pem` files must be created with `chmod 400` immediately after writing
- Security group allows inbound TCP 22 only; all other ports closed by default

## Do Not
- Do not use `print()` — use `rich` Console
- Do not create boto3 clients outside `credentials.py`
- Do not hardcode AMI IDs — fetch latest Amazon Linux 2023 via `describe_images` with owner `amazon`
- Do not delete rows from `hosts.json` — mark as `terminated` instead
- Do not commit `credentials.json`, `.pem` files, or `hosts.json`
