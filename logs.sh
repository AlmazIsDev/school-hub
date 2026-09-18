#!/usr/bin/env bash
# Логи всех сервисов compose (или выбранных: ./logs.sh api bot).
# -f — следить в реальном времени, как tail -f.
cd "$(dirname "$0")"
exec docker compose logs -f --tail=1000 "$@"
