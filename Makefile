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

# --- iOS ------------------------------------------------------------------------------
# The Swift chain is SEPARATE from the Python and TypeScript ones and runs only on macOS.
# Order is load-bearing here as in the other two: from S2b, `crap_swift.py` reads the
# coverage `swift test` writes, so tests run before the gate.

.PHONY: ios-export ios-fixtures ios-field-coverage ios-qa

IOS_STORE := apps/ios/Sources/SwimZHKit/Resources/ios.sqlite
IOS_DESTINATION ?= platform=iOS Simulator,name=iPhone 17

ios-export:  ## Project the LIVE gold store into the bundled iOS store (the release path)
	uv run python -m swimzh.cli export-ios --db gold.sqlite --out $(IOS_STORE)

ios-fixtures:  ## Regenerate the COMMITTED offline store + geo fixture (no network, deterministic)
	uv run python scripts/ios_fixtures.py

# The field-coverage contract the phone is measured against. Staleness-gated by
# `apps/web/tests/test_field_coverage_contract.py`, so this target is a convenience: the gate
# fails either way, and its message names the pytest form.
ios-field-coverage:  ## Regenerate field_coverage.json from the pydantic response models
	uv run python scripts/field_coverage.py

# The lint covers `App` as well as the package: `swift build` compiles only the package, so
# without it the SwiftUI layer — the one S3a grows most — would never be linted at all.
#
# The closing `xcodebuild ... test` carries THREE things `swift test` structurally cannot:
# the app target's compile check, the app-hosted metric/correctness tests, and — as the app
# target's last build phase — `scripts/ios_budget.py`, so a size regression fails right
# there rather than needing a step of its own to remember.
#
# `pytest tests/scripts` runs HERE and not only in the Python chain, because two of the
# gate's own tests — the CRAP offender path and the coverage join — skip without
# `apps/ios/.build`, which the ubuntu `qa` job never has. Without this step they would be
# dead code in CI on every runner. It goes after the CRAP step so the build directory and
# the coverage data exist, and `--no-cov` because the coverage floor belongs to the Python
# chain alone and must not be computed from this partial selection.
ios-qa:  ## Swift chain: format lint -> build -> test+coverage -> CRAP -> gate tests -> simulator test
	cd apps/ios && swift format lint --strict --recursive Sources Tests App
	cd apps/ios && swift build
	cd apps/ios && swift test --enable-code-coverage
	uv run python scripts/crap_swift.py
	uv run pytest tests/scripts --no-cov
	cd apps/ios && xcodebuild -project App/SwimZH.xcodeproj -scheme SwimZH \
		-destination '$(IOS_DESTINATION)' test
	@echo "iOS QA: all green"
