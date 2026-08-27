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

.PHONY: ios-export ios-fixtures ios-field-coverage ios-locales ios-locales-check ios-qa

IOS_STORE := apps/ios/Sources/SwimZHKit/Resources/ios.sqlite
IOS_RELEASE_DIR ?= dist/ios
IOS_DESTINATION ?= platform=iOS Simulator,name=iPhone 17

# Deliberately writes to the RELEASE dir, never to $(IOS_STORE). Those are two different
# artifacts that briefly shared one path, and the sharing was a trap: $(IOS_STORE) is the
# COMMITTED, deterministic, offline 140-day fixture that every Swift golden and lane test is
# generated against, while this target projects the LIVE 400-day gold store. Running this
# against $(IOS_STORE) silently replaced the fixture with live data and failed ten Swift
# tests with a 200-line lane-strip diff that looked like a code defect. Regenerate the
# fixture with `make ios-fixtures`; build a shippable store with this or `ios-release`.
ios-export:  ## Project the LIVE gold store into a RELEASE store (never the committed fixture)
	mkdir -p $(IOS_RELEASE_DIR)
	uv run python -m swimzh.cli export-ios --db gold.sqlite --out $(IOS_RELEASE_DIR)/ios.sqlite

ios-fixtures:  ## Regenerate the COMMITTED offline store + geo fixture (no network, deterministic)
	uv run python scripts/ios_fixtures.py

# The web's message catalogs, projected into the iOS string catalog. NOT a second catalog:
# `apps/web/static/js/locales/*.ts` is the source of truth for every sentence this product
# says, and `Localizable.xcstrings` is derived from it exactly as `data/catalog.json` is
# derived from the WFS. The converter is node because the catalogs are TypeScript modules and
# it imports the COMPILED `dist/locales/*.js` — so the TS build comes first.
# Staleness-gated by `tests/scripts/test_locales_to_xcstrings.py`, which skips without `dist/`.
ios-locales:  ## Regenerate Localizable.xcstrings + Catalog.generated.swift from the web catalogs
	npm --prefix apps/web/static/js run build
	node scripts/locales_to_xcstrings.mjs

# The GATE, and the difference from `ios-locales` is the whole point: this one never writes.
# `ios-qa` used to run the regenerating target and then assert the result matched — which
# compared generator output against generator output and could not fail. A contributor could
# edit a sentence in `en.ts`, not regenerate, and ship a phone catalog saying the old thing with
# every chain green. This builds the TS (so `dist/locales/*.js` exists and the converter's
# pytest stops skipping) and then CHECKS, so a stale committed catalog fails the chain.
ios-locales-check:  ## Fail if the committed iOS catalog is stale against the web catalogs
	npm --prefix apps/web/static/js run build
	node scripts/locales_to_xcstrings.mjs --check

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
# `ios-locales-check` runs FIRST, and it CHECKS rather than writes. `dist/locales/*.js` is
# git-ignored, so without the TS build the converter's staleness test skips and acceptance 1 is
# unasserted; with a REGENERATING step, the check that follows compares generator output against
# generator output and cannot fail either. Building and then `--check`ing is the only order in
# which a stale committed catalog is caught: `node scripts/locales_to_xcstrings.mjs --check`
# diffs the two generated files against what is on disk, i.e. against what is committed.
#
# `pytest tests/scripts` runs HERE and not only in the Python chain, because two of the
# gate's own tests — the CRAP offender path and the coverage join — skip without
# `apps/ios/.build`, which the ubuntu `qa` job never has. Without this step they would be
# dead code in CI on every runner. It goes after the CRAP step so the build directory and
# the coverage data exist, and `--no-cov` because the coverage floor belongs to the Python
# chain alone and must not be computed from this partial selection.
ios-qa:  ## Swift chain: locale check -> format lint -> build -> test+coverage -> CRAP -> gate tests -> simulator test
	$(MAKE) ios-locales-check
	cd apps/ios && swift format lint --strict --recursive Sources Tests App
	cd apps/ios && swift build
	cd apps/ios && swift test --enable-code-coverage
	uv run python scripts/crap_swift.py
	uv run pytest tests/scripts --no-cov
	$(MAKE) ios-sim-world
	cd apps/ios && xcodebuild -project App/SwimZH.xcodeproj -scheme SwimZH \
		-destination '$(IOS_DESTINATION)' test
	@echo "iOS QA: all green"

# --- the weekly release ---------------------------------------------------------------------
#
# ONE command produces the two files a release needs: the pre-resolved store and the manifest
# that describes it. Every manifest field is read back OUT of the finished store, so the two
# cannot disagree — which is the whole of S5 acceptance 5.
#
# WHERE they are uploaded is deliberately not this repo's business (hosting is out of scope in
# the plan), so `IOS_STORE_URL` has no default: a manifest carrying a placeholder URL is one
# every installed phone would fetch, fail on, and retry forever. The export refuses without it.
#
# The release store is written OUTSIDE the package's Resources on purpose. The committed
# resource is the OFFLINE FLOOR — a small, deterministic, cassette-built store the test suite
# replays against — and overwriting it with a live 400-day export would swap a reproducible
# fixture for one that moves with the wall clock. `make ios-export` is the command that does
# that deliberately.
IOS_STORE_URL ?=

.PHONY: ios-sim-world
# The world `BehaviourTests.testMyLocationChangesWhatNearestMeans` needs, granted from OUTSIDE
# the app. An XCUITest runs ON the simulator, so it cannot shell out (`Process` is macOS-only),
# and the permission alert belongs to SpringBoard rather than to this app — tapping it is slow,
# famously flaky, and tests whether iOS can draw its own dialog rather than what this app does
# with the answer.
#
# WOLLISHOFEN, and the coordinates are load-bearing: it is about four kilometres south of Zürich
# HB, which is what `Places.default` measures from. A position near the station would leave both
# orderings identical and the test would pass while proving nothing. `- ` prefixes because a
# device that is not booted must not fail the whole chain — but the GRANT itself is not
# tolerated: if it silently failed, `testMyLocationChangesWhatNearestMeans` would exercise the
# refusal path while claiming to prove the fix path, which is a green gate proving the opposite
# of what it says. Only the boot lines are optional, because a device already booted makes
# `simctl boot` exit non-zero and that is the normal local case.
IOS_SIM ?= iPhone 17
ios-sim-world:  ## Boot the simulator, grant location and place it, for the behaviour tests
	-xcrun simctl boot "$(IOS_SIM)"
	-xcrun simctl bootstatus "$(IOS_SIM)"
	xcrun simctl privacy booted grant location ch.swimzh.SwimZH
	xcrun simctl location booted set 47.3450,8.5340

.PHONY: ios-release

ios-release:  ## Build the release store + manifest.json (IOS_STORE_URL=https://… required)
	@test -n "$(IOS_STORE_URL)" || { \
		echo "IOS_STORE_URL is required: make ios-release IOS_STORE_URL=https://host/path/ios.sqlite"; \
		exit 2; }
	mkdir -p $(IOS_RELEASE_DIR)
	uv run python -m swimzh.cli export-ios --db gold.sqlite \
		--out $(IOS_RELEASE_DIR)/ios.sqlite \
		--manifest $(IOS_RELEASE_DIR)/manifest.json \
		--url '$(IOS_STORE_URL)'
