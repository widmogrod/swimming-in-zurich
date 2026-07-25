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
    rules: {
      "@typescript-eslint/no-unsafe-argument": "error",
      "@typescript-eslint/no-unsafe-assignment": "error",
      "@typescript-eslint/no-unsafe-call": "error",
      "@typescript-eslint/no-unsafe-member-access": "error",
      "@typescript-eslint/no-unsafe-return": "error",
    },
  },
);
