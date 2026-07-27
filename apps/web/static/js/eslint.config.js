import i18next from "eslint-plugin-i18next";
import tseslint from "typescript-eslint";

// Scoped to migrated TypeScript during the migration window: the ~60 legacy `.js` files
// were never eslint/prettier-formatted, so linting them here is out of scope. Each file
// joins this scope as it converts to `.ts`; the legacy ignore shrinks to nothing when
// migration completes.
//
// Type-aware rules need a program spanning source AND tests. Tests live only in
// `tsconfig.dev.json` (the emit `tsconfig.json` excludes `*.test.ts`), so the parser is
// pointed at the dev config rather than `projectService: true` (which keys off
// `tsconfig.json` and would reject the test file).
export default tseslint.config(
  { ignores: ["**/*.js", "node_modules/", "coverage/"] },
  {
    files: ["**/*.ts"],
    extends: [...tseslint.configs.recommended],
    languageOptions: {
      parserOptions: {
        project: ["./tsconfig.dev.json"],
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: { i18next },
    rules: {
      // The S7 ratchet: a hardcoded user-visible string must not creep back in.
      //
      // `mode: "all"` is REQUIRED — since v5 the rule defaults to JSX markup text, and
      // this codebase builds DOM imperatively (`el.textContent = "…"`), so the default
      // mode would see nothing at all.
      //
      // The price of `all` is that machine values are literals too: CSS classes, ARIA
      // attribute names, tag names, event names. Those must never reach a translator, so
      // they are excluded BY CALL SITE below rather than by wording.
      //
      // NOTE the patterns are SUFFIX-anchored (`setAttribute$`), not `^…$`: the rule
      // matches the full callee text, so `el.setAttribute` never matches `^setAttribute$`.
      // A spike caught this — with `^…$` the config silently excluded nothing and the rule
      // reported 1294 "violations" that were all machine values.
      "i18next/no-literal-string": [
        "error",
        {
          mode: "all",
          "should-validate-template": true,
          callees: {
            exclude: [
              "^t$", // the message lookup itself
              // --- DOM plumbing: attribute/class/event names are machine values -------
              "setAttribute$",
              "getAttribute$",
              "hasAttribute$",
              "removeAttribute$",
              "classList\\.(add|remove|toggle|contains)$",
              "addEventListener$",
              "removeEventListener$",
              "createElement$",
              "getElementById$",
              "querySelector$",
              "querySelectorAll$",
              "getPropertyValue$",
              "getContext$",
              "matchMedia$",
              "dispatch$",
              // --- string/collection plumbing ----------------------------------------
              "(includes|startsWith|endsWith|split|join|replace|match|padStart)$",
              "(localeCompare|toBe|toEqual|toMatch|toContain)$",
              "(has|get|set|delete|push|indexOf|find|filter|some|every)$",
              // --- canvas + history --------------------------------------------------
              "setLineDash$",
              "fillText$",
              "(pushState|replaceState)$",
              // --- our own machine-value factories -----------------------------------
              // Every one of these takes an ID, a CSS class, a state key or a URL —
              // never copy. Excluded by CALL SITE so the rule keeps watching everything
              // else in the same file.
              "iconSvg$",
              "(mustEl|newEl|asEl|asDoc)$", // DOM ids / tag names
              "setDashes$", // 'solid' | 'dashed' | 'dotted' — a line style
              "swatchRow$", // CSS class + an already-translated label
              "readJSON$", // element id of an embedded JSON block
              "fallbackTo$", // a machine reason key, rendered via the catalogue
              "^fetch$", // API paths
              "(TypeError|RangeError)$", // developer-facing invariant messages
              "^(Set|Map|Error|URL|URLSearchParams|Number|String|JSON)$",
            ],
          },
          // The machine VOCABULARY: lowercase state keys, message-key prefixes, URL
          // fragments and DOM id stems. These are values the code branches on, never
          // words a reader sees — a translator handed "lanes-unknown" would have no idea
          // what to do with it. Case-sensitive on purpose: `pool` is a mode key, while
          // `Pool` was a user-visible fallback (and the rule caught it).
          words: {
            exclude: [
              "^(open|closed|unknown|uncurated|lanes|lanes-unknown)$",
              "^(pool|day|date|week|auto|default|other|solid|dashed|dotted)$",
              "^(light|dark|female|male|diverse|adult|youth|child|senior)$",
              "^(closure|holiday|price|access|status)\\.$",
              "^/(swim|pools)", // API paths
              "^ui-combo", // generated element id stems
            ],
          },
          // Property KEYS and class fields are identifiers, never copy.
          "object-properties": { exclude: [".*"] },
          "class-properties": { exclude: [".*"] },
        },
      ],
      "@typescript-eslint/no-unsafe-argument": "error",
      "@typescript-eslint/no-unsafe-assignment": "error",
      "@typescript-eslint/no-unsafe-call": "error",
      "@typescript-eslint/no-unsafe-member-access": "error",
      "@typescript-eslint/no-unsafe-return": "error",
    },
  },
  {
    // The copy ratchet applies to SHIPPED code only. A test asserting
    // `expect(row.textContent).toBe("Summer break")` is supposed to contain that literal —
    // that is the assertion. Fixtures and CSS selectors likewise. Running the rule over
    // tests produced 375 "violations", none of them copy.
    files: ["**/*.test.ts"],
    rules: { "i18next/no-literal-string": "off" },
  },
);
