.PHONY: autofix inspection typecheck preflight test test\:backend test\:frontend test\:integration

autofix:
	uv run ruff check --fix
	uv run ruff format

inspection:
	uv run ruff check
	uv run ruff format --check

typecheck:
	uv run ty check

preflight: inspection typecheck

test:
	uv run pytest

test\:backend:
	uv run pytest backend/

test\:frontend:
	uv run pytest frontend/

test\:integration:
	uv run pytest integration/
