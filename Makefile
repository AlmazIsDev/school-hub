infra:
	docker compose up -d mongo redis
up:
	docker compose up -d --build
# локальная разработка: make dev поднимает mongo/redis, uvicorn и vite сразу;
# бот запускается отдельно (make bot)
dev: infra
	$(MAKE) -j2 dev-backend dev-frontend
dev-backend: infra
	cd backend && uvicorn app.main:app --reload
dev-frontend: infra
	cd frontend && npm run dev
bot: infra
	cd backend && python -m app.bot
