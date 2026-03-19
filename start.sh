#!/bin/bash
# Pre-create data files so Docker bind mounts work correctly on first run
touch hosts.json llm_log.jsonl bridge_config.json
mkdir -p sessions keys/deleted

# Data dirs must be owned by uid 1000 (container user)
sudo chown -R 1000:1000 sessions/ keys/ hosts.json llm_log.jsonl bridge_config.json 2>/dev/null || true

docker compose up --build "$@"
