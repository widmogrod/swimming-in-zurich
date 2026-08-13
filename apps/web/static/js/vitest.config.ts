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
        "**/*.d.ts",
        "node_modules/**",
        "coverage/**",
        // --- BROWSER ENTRYPOINTS -------------------------------------------------
        // These four modules are wiring, not logic: they read the real `document`,
        // call fetch/history, and only ever run inside a browser. There is nothing
        // to unit-test that is not either (a) already extracted into appdata.ts and
        // tested there, or (b) a DOM/network side effect.
        //
        // The same judgement `apps/web/main.py` makes with `# pragma: no cover` on
        // `_build_static_assets`. Every module holding a RULE stays measured — the
        // pure transforms behind app.ts live in appdata.ts precisely so they are.
        //
        // The two `*_preview` files and `gallery` are additionally dev-only surfaces
        // (SWIMZH_DEV_UI), 404 in production.
        //
        // Narrow this list, never widen it: a new rule belongs in a measured module.
        "app.ts",
        "components/gallery.ts",
        "blocks/board_preview.ts",
        "blocks/detail_preview.ts",
      ],
    },
  },
});
