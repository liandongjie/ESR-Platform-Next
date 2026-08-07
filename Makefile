.PHONY: up down logs backend-test backend-lint frontend-check

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

backend-test:
	cd backend && pytest

backend-lint:
	cd backend && ruff check .

frontend-check:
	cd frontend && npm run type-check && npm run lint && npm run test:run && npm run build
