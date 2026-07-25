import { defineConfig } from "vitest/config";

// The migrated TS suites run on vitest; the legacy `.js` suites stay on `node --test`
// (the pytest bridge). `urlstate` is pure, so the `node` environment suffices (no DOM);
// a `jsdom` env is added later for DOM-touching modules as they migrate.
export default defineConfig({
  test: {
    environment: "node",
    include: ["**/*.test.ts"],
    coverage: {
      provider: "v8",
      // `json` writes coverage/coverage-final.json (Istanbul-shaped) — the CRAP input.
      reporter: ["text", "json"],
      // `all` puts EVERY source .ts in coverage-final.json (a never-executed file gets a
      // 0-hit statementMap + an `(empty-report)` fnMap). crap_ts.mjs scores such a file via
      // its whole-file coverage fallback (→ 0%), so an untested high-complexity module cannot
      // hide from the CRAP gate — the same reason coverage.py measures the whole `source` tree.
      all: true,
      // Only migrated TS is measured; configs and the tests themselves are excluded.
      include: ["**/*.ts"],
      exclude: [
        "**/*.test.ts",
        "**/*.config.ts",
        "node_modules/**",
        "coverage/**",
      ],
    },
  },
});
