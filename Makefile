# QA chain for swimzh. Order matters: crap reads the coverage.json that pytest writes,
# so `test` must run before `crap` (the `qa` target enforces this).

.PHONY: qa lint fmt fmt-check type test crap install hooks

install:  ## Sync the environment (incl. dev tools)
	uv sync

lint:  ## Ruff lint
	uv run ruff check .

fmt:  ## Ruff format (write)
	uv run ruff format .

fmt-check:  ## Ruff format (check only)
	uv run ruff format --check .

type:  ## mypy strict
	uv run mypy .

test:  ## pytest (writes coverage.json, enforces coverage floor)
	uv run pytest

crap:  ## CRAP complexity/coverage gate (run AFTER test)
	uv run python scripts/crap.py

qa: lint fmt-check type test crap  ## Full chain, in order
	@echo "QA: all green"

hooks:  ## Install pre-commit + pre-push git hooks
	uv run pre-commit install --install-hooks
