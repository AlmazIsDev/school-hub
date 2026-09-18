#!/usr/bin/env bash
# Дев-старт: mongo+redis в compose, затем бэк и фронт одновременно.
# Остановка по Ctrl+C гасит всё.
set -e
cd "$(dirname "$0")"

# Порты из .env (compose читает его сам, сюда — для uvicorn и vite)
if [ -f .env ]; then
  set -a; source .env; set +a
fi
API_PORT="${API_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
# В .env URL под docker-сеть (хосты mongo/redis); локальным процессам нужны localhost
export MONGO_URL="mongodb://localhost:${MONGO_PORT:-27017}/schoolhub"
export REDIS_URL="redis://localhost:${REDIS_PORT:-6379}/0"

docker compose up -d mongo redis

cleanup() {
  kill 0 2>/dev/null
}
trap cleanup EXIT

(cd backend && uvicorn app.main:app --reload --port "$API_PORT") &
(cd frontend && npm run dev -- --port "$FRONTEND_PORT") &

wait
