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

.PHONY: ios-export ios-fixtures ios-field-coverage ios-locales ios-locales-check ios-qa \
        ios-lint ios-build ios-test ios-crap ios-gate-tests ios-sim-test

IOS_STORE := apps/ios/Sources/SwimZHKit/Resources/ios.sqlite
IOS_RELEASE_DIR ?= dist/ios
# ONE device name, and `IOS_DESTINATION` is DERIVED from it. They were two independent
# copies, which is a trap with no error message: `ios-sim-world` grants location to the
# simulator named by one, `xcodebuild` runs the tests on the simulator named by the other, so
# overriding a single variable would leave the behaviour test exercising the location-refusal
# path on an ungranted device while claiming to prove the grant path.
IOS_SIM ?= iPhone 17
IOS_DESTINATION ?= platform=iOS Simulator,name=$(IOS_SIM)

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
#
# Each step is its own target, and CI's `ios-qa` job calls THESE rather than re-typing the
# commands. The job was a hand transcription — it agreed with this recipe step for step and
# nothing said it had to, so the destination string lived in three places and a change here
# could leave CI running something else while both stayed green. One name per step keeps the
# job's per-step reporting (a red step says which gate failed) without a second copy of the
# command it runs.
ios-lint:  ## swift format lint, package AND app
	cd apps/ios && swift format lint --strict --recursive Sources Tests App

ios-build:  ## Build the SwiftPM package
	cd apps/ios && swift build

ios-test:  ## Test the package with the coverage the CRAP gate reads
	cd apps/ios && swift test --enable-code-coverage

ios-crap:  ## The Swift CRAP gate (reads the coverage `ios-test` wrote)
	uv run python scripts/crap_swift.py

ios-gate-tests:  ## The gates' OWN tests, which need `apps/ios/.build` to exist
	uv run pytest tests/scripts --no-cov

ios-sim-test:  ## Build + test the app target in the simulator (also runs the size ratchet)
	cd apps/ios && xcodebuild -project App/SwimZH.xcodeproj -scheme SwimZH \
		-destination '$(IOS_DESTINATION)' \
		-skip-testing:SwimZHUITests/ScreenshotTests \
		test

ios-qa:  ## Swift chain: locale check -> format lint -> build -> test+coverage -> CRAP -> gate tests -> simulator test
	$(MAKE) ios-locales-check
	$(MAKE) ios-lint
	$(MAKE) ios-build
	$(MAKE) ios-test
	$(MAKE) ios-crap
	$(MAKE) ios-gate-tests
	$(MAKE) ios-sim-world
	$(MAKE) ios-sim-test
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
#
# `IOS_SIM` is declared once, up with `IOS_DESTINATION` — which is derived from it, so this
# target and `xcodebuild` cannot be pointed at two different simulators.
#
# THE APP IS INSTALLED BEFORE IT IS GRANTED, and the order is the whole target. `simctl privacy
# grant` writes a TCC entry for a bundle id, and installing an app that was not there creates a
# FRESH one — so granting first and letting `xcodebuild test` install afterwards throws the
# grant away. That is not theory: it is why CI failed on a runner while the same command passed
# here, and it reproduces locally the moment you `simctl uninstall` first. Every local green
# before this was an accident of the app already being installed from a previous run.
#
# The path comes from `-showBuildSettings` rather than a hardcoded DerivedData guess, because
# that directory is hashed per checkout location and differs between this machine and a runner.
ios-sim-world:  ## Boot, build, install and permit the simulator, for the behaviour tests
	-xcrun simctl boot "$(IOS_SIM)"
	-xcrun simctl bootstatus "$(IOS_SIM)"
	cd apps/ios && xcodebuild -project App/SwimZH.xcodeproj -scheme SwimZH \
		-destination '$(IOS_DESTINATION)' build-for-testing
	xcrun simctl install booted "$$(cd apps/ios && xcodebuild -project App/SwimZH.xcodeproj \
		-scheme SwimZH -destination '$(IOS_DESTINATION)' -showBuildSettings 2>/dev/null \
		| awk -F' = ' '/ TARGET_BUILD_DIR =/{d=$$2} / FULL_PRODUCT_NAME =/{n=$$2} \
		  END{print d"/"n}')"
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

.PHONY: ios-screenshots

# The App Store screenshot set. SEPARATE from `ios-qa` on purpose, and skipped by name in
# `ios-sim-test` above: it runs on a 6.9" device the rest of the chain does not use, and it
# proves no behaviour of its own — `BehaviourTests` already owns every gesture it performs.
#
# 6.9" IS THE ONLY SIZE APPLE STILL REQUIRES (1320 x 2868); it scales that set down for
# every smaller device, so one simulator is the whole submission.
IOS_SHOT_SIM ?= iPhone 17 Pro Max
IOS_SHOT_DIR ?= dist/screenshots
IOS_SHOT_RESULT := dist/screenshots.xcresult

ios-screenshots:  ## Capture the App Store screenshot set into dist/screenshots/
	# THE APP'S CLOCK IS THE HOST'S, and there is no seam to fake it — `TodayModel.load(now:)`
	# takes the date but the app wires `Date()`. So a capture at 01:00 photographs the honest
	# but unsellable headline "Nothing open to you now", which is how the first run of this
	# target ended. Refusing beats uploading it: the App Store shows the first screenshot
	# before anything else, and nobody re-reads a set they believe they already took.
	# The window is the POOLS' hours, not office hours: Hallenbad City runs 06:00-22:00, so a
	# 19:00 capture still says "N pools open to you now". 21:00 is the first hour at which
	# little enough is left that the set stops selling the app.
	@hour=$$(date +%H); \
	if [ "$$hour" -lt 09 ] || [ "$$hour" -ge 21 ]; then \
		echo "make ios-screenshots: it is $$hour:00 — too little is open, so the first"; \
		echo "screenshot would read \"Nothing open to you now\". Run between 09:00 and 21:00."; \
		exit 2; \
	fi
	-xcrun simctl boot "$(IOS_SHOT_SIM)"
	-xcrun simctl bootstatus "$(IOS_SHOT_SIM)"
	# BY NAME, NOT `booted`. With two simulators up — and `ios-sim-world` boots another one —
	# `booted` is ambiguous, and the first run of this target sent the override to the wrong
	# device and photographed the real clock.
	#
	# Apple's own 09:41, full battery, full bars. Not vanity: a real status bar puts a battery
	# percentage and a carrier name in a store screenshot, and both read as clutter a reviewer
	# notices before they notice the app.
	xcrun simctl status_bar "$(IOS_SHOT_SIM)" override \
		--time "09:41" --batteryState charged --batteryLevel 100 \
		--cellularBars 4 --wifiBars 3
	rm -rf "$(IOS_SHOT_DIR)" "$(IOS_SHOT_RESULT)"
	cd apps/ios && xcodebuild -project App/SwimZH.xcodeproj -scheme SwimZH \
		-destination 'platform=iOS Simulator,name=$(IOS_SHOT_SIM)' \
		-only-testing:SwimZHUITests/ScreenshotTests \
		-resultBundlePath "$(CURDIR)/$(IOS_SHOT_RESULT)" \
		test
	# The screenshots are ATTACHMENTS inside the result bundle, not files — which is why the
	# test marks them `.keepAlways`, the default lifetime deleting them on a passing run.
	mkdir -p "$(IOS_SHOT_DIR)"
	xcrun xcresulttool export attachments \
		--path "$(IOS_SHOT_RESULT)" --output-path "$(IOS_SHOT_DIR)"
	# xcresulttool names every file after its attachment UUID and puts the name the test chose
	# in manifest.json beside them. Unrenamed, the five shots sort at random and the upload
	# order — which IS the order Apple shows them in — becomes whatever the filesystem says.
	uv run python scripts/name_screenshots.py "$(IOS_SHOT_DIR)"
