#!/bin/bash
# Pre-create data files so Docker bind mounts work correctly on first run
touch hosts.json llm_log.jsonl bridge_config.json
mkdir -p sessions keys/deleted

docker compose up --build "$@"
