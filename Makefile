infra:
	docker compose up -d mongo redis
up:
	docker compose up -d --build
dev: infra
	cd backend && uvicorn app.main:app --reload
bot: infra
	cd backend && python -m app.bot
