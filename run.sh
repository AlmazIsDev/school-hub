#!/usr/bin/env bash
# Дев-старт: postgres+redis в compose, затем бэк и фронт одновременно.
# Остановка по Ctrl+C гасит всё.
set -e
cd "$(dirname "$0")"

docker compose up -d postgres redis

cleanup() {
  kill 0 2>/dev/null
}
trap cleanup EXIT

(cd backend && uvicorn app.main:app --reload) &
(cd frontend && npm run dev) &

wait
