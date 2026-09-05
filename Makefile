.PHONY: init config up down restart ps logs smoke test-backend check-ui

init:
	@test -f .env || cp .env.example .env
	@echo "Edit .env and fill the required secrets before starting the stack."

config:
	docker compose config --quiet

up:
	docker compose up --build --detach

down:
	docker compose down

restart:
	docker compose restart

ps:
	docker compose ps

logs:
	docker compose logs --follow --tail=200

smoke:
	docker compose exec -T postgres sh -ec 'pg_isready -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'
	docker compose exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
	docker compose exec -T backend python -c "import json, urllib.request; paths=json.load(urllib.request.urlopen('http://127.0.0.1:8000/openapi.json', timeout=3))['paths']; assert '/api/v1/auth/telegram/start' in paths; assert '/api/v1/candidates/{candidate_id}/analysis/questions/{question_id}/review' in paths"
	docker compose exec -T postgres sh -ec 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM workflow_users" >/dev/null'
	docker compose exec -T ui node -e "fetch('http://127.0.0.1:3000').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"
	docker compose run --rm --no-deps --entrypoint /bin/sh minio-init -ec 'mc alias set local http://minio:9000 "$$MINIO_ROOT_USER" "$$MINIO_ROOT_PASSWORD" >/dev/null; mc stat "local/$$S3_BUCKET" >/dev/null'
	@echo "Infrastructure smoke checks passed."

test-backend:
	cd backend && python -m pytest && python -m ruff check .

check-ui:
	cd ui && pnpm exec tsc --noEmit --incremental false && pnpm run lint
