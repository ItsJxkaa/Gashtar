#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
python3 deploy/init_env.py
python3 deploy/verify_engine.py
docker compose version
nvidia-smi
docker compose config --quiet
docker compose build model analyzer web
docker compose --profile setup run --rm model-download
docker compose up -d
printf '%s\n' 'Services started. Check: docker compose ps' 'HTTPS URL: docker compose logs cloudflared' 'API key (private): cat .env'
