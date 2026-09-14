.PHONY: up down build logs test-run preview health clean

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose up -d --build

logs:
	docker compose logs -f backend

health:
	@curl -s http://localhost:8585/api/health

preview:
	@curl -s -X POST http://localhost:8585/api/pipeline/preview | python3 -m json.tool

send-now:
	@curl -s -X POST http://localhost:8585/api/pipeline/send-now | python3 -m json.tool

test-run:
	@docker compose exec backend python3 -c "import asyncio; from app.services.pipeline import run_pipeline; print(asyncio.run(run_pipeline(dry_run=True)))"

clean:
	docker compose down -v
