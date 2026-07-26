#!/usr/bin/env node
// CRAP gate for the TypeScript UI — FORMULA parity with scripts/crap.py:
//
//     CRAP(f) = cc(f)^2 * (1 - cov(f))^3 + cc(f)
//
// High complexity with low test coverage = change risk. Complexity comes from
// ESLint's built-in `complexity` rule (run at threshold 0 so every function is
// reported); per-function coverage is derived from the Istanbul-shaped
// `coverage-final.json` vitest writes — so run `vitest run --coverage` FIRST,
// this gate is stale without it (mirrors "pytest before crap").
//
// Parity is FORMULA parity, not metric parity: ESLint's cyclomatic count and
// radon's differ algorithmically, so `[tool.crap-ts]` is its own ratchet.
// Config in pyproject.toml (CLI flags override):
//
//     [tool.crap-ts]
//     threshold = 30.0        # functions scoring above this fail the gate
//     min-complexity = 5      # functions at or below this cc are never flagged
//
// Exits 1 when any function has cc > min-complexity AND crap > threshold.
// Scores SOURCE `.ts` only (excludes `*.test.ts` and `*.config.ts`), matching
// crap.py scoring `src`, not tests.

import { execFileSync } from 'node:child_process';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const JS_DIR = join(REPO_ROOT, 'apps', 'web', 'static', 'js');
const COVERAGE_JSON = join(JS_DIR, 'coverage', 'coverage-final.json');
const PYPROJECT = join(REPO_ROOT, 'pyproject.toml');

const DEFAULT_THRESHOLD = 30.0;
const DEFAULT_MIN_COMPLEXITY = 5;

/** crap = cc**2 * (1 - cov)**3 + cc — identical to scripts/crap.py. */
function crapScore(cc, cov) {
  const uncovered = 1.0 - cov;
  return cc * cc * uncovered ** 3 + cc;
}

/** Minimal read of `[tool.crap-ts]` from pyproject (threshold, min-complexity). */
function loadConfig() {
  let threshold = DEFAULT_THRESHOLD;
  let minComplexity = DEFAULT_MIN_COMPLEXITY;
  let body;
  try {
    body = readFileSync(PYPROJECT, 'utf-8');
  } catch {
    return { threshold, minComplexity };
  }
  const section = body.match(/\[tool\.crap-ts\]([\s\S]*?)(\n\[|\s*$)/);
  if (section) {
    const t = section[1].match(/threshold\s*=\s*([\d.]+)/);
    const m = section[1].match(/min-complexity\s*=\s*(\d+)/);
    if (t) threshold = parseFloat(t[1]);
    if (m) minComplexity = parseInt(m[1], 10);
  }
  return { threshold, minComplexity };
}

/** Source `.ts` files (recursively) under JS_DIR, excluding tests and configs. */
function sourceTsFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name === 'coverage') continue;
      out.push(...sourceTsFiles(full));
    } else if (
      entry.name.endsWith('.ts') &&
      !entry.name.endsWith('.test.ts') &&
      !entry.name.endsWith('.config.ts')
    ) {
      out.push(full);
    }
  }
  return out;
}

/** file -> Map(startLine -> {cc, name}), from ESLint's `complexity` rule at threshold 0.
 * ESLint is the PRIMARY source of the function list (every source function), so a function
 * can never be silently dropped for lack of a coverage entry (crap.py likewise iterates its
 * complexity tool, then looks coverage up). */
function complexityByFile(files) {
  if (files.length === 0) return new Map();
  let stdout = '';
  try {
    stdout = execFileSync(
      'npx',
      ['eslint', ...files, '--rule', '{"complexity":["warn",0]}', '--format', 'json'],
      { cwd: JS_DIR, encoding: 'utf-8', maxBuffer: 64 * 1024 * 1024 },
    );
  } catch (err) {
    // ESLint exits non-zero if any file has an error-level lint problem; the JSON
    // report is still on stdout, so parse it rather than aborting the gate.
    stdout = err.stdout ? err.stdout.toString() : '';
    if (!stdout) throw err;
  }
  const report = JSON.parse(stdout);
  const byFile = new Map();
  for (const fileReport of report) {
    const perLine = new Map();
    for (const msg of fileReport.messages) {
      if (msg.ruleId !== 'complexity') continue;
      const m = msg.message.match(/complexity of (\d+)/);
      if (!m) continue;
      const named = msg.message.match(/Function '([^']+)'/);
      perLine.set(msg.line, {
        cc: parseInt(m[1], 10),
        name: named ? named[1] : `(anonymous:${msg.line})`,
      });
    }
    byFile.set(resolve(fileReport.filePath), perLine);
  }
  return byFile;
}

/** covered / total statements whose start line falls within [lo, hi] (1.0 when none). */
function coverageInSpan(fileCov, lo, hi) {
  let covered = 0;
  let total = 0;
  for (const [sid, stmtLoc] of Object.entries(fileCov.statementMap)) {
    const line = stmtLoc.start.line;
    if (line < lo || line > hi) continue;
    total += 1;
    if (fileCov.s[sid] > 0) covered += 1;
  }
  return total === 0 ? 1.0 : covered / total;
}

/** Whole-file statement coverage — the fallback for a function with no per-function
 * `fnMap` span (an untested file whose v8 `fnMap` is just `(empty-report)`, or a join
 * miss). For a never-executed file every statement is 0-hit → 0%, so a high-complexity
 * untested module CANNOT hide from the gate. */
function fileCoverage(fileCov) {
  const ids = Object.keys(fileCov.statementMap);
  if (ids.length === 0) return 1.0;
  let covered = 0;
  for (const id of ids) if (fileCov.s[id] > 0) covered += 1;
  return covered / ids.length;
}

function collectScores(complexity, coverage) {
  const covByPath = new Map();
  for (const [p, fc] of Object.entries(coverage)) covByPath.set(resolve(p), fc);

  const scores = [];
  for (const [absPath, fnByLine] of complexity) {
    const fileCov = covByPath.get(absPath);
    // A file ABSENT from coverage-final.json was deliberately excluded from measurement
    // in vitest.config.ts (the browser entrypoints), so it is not scored — exactly as
    // crap.py never sees a module that coverage.py `omit`s or `# pragma: no cover`s.
    // This is NOT the untested-file case: `coverage.all: true` lists every measured
    // source file, so an untested one IS present (with an `(empty-report)` fnMap) and
    // still falls through to the 0% whole-file path below.
    if (!fileCov) continue;
    // Real per-function spans (drop v8's `(empty-report)` placeholder), keyed by start line.
    const spanByLine = new Map();
    if (fileCov) {
      for (const fn of Object.values(fileCov.fnMap)) {
        if (fn.name === '(empty-report)') continue;
        spanByLine.set(fn.decl?.start?.line ?? fn.line, fn.loc);
      }
    }
    for (const [line, { cc, name }] of fnByLine) {
      let cov;
      const loc = spanByLine.get(line);
      if (loc) cov = coverageInSpan(fileCov, loc.start.line, loc.end.line);
      else cov = fileCoverage(fileCov); // no span → file-level (0% when untested)
      scores.push({ path: absPath, line, name, cc, cov, crap: crapScore(cc, cov) });
    }
  }
  return scores;
}

function pct(x) {
  return `${Math.round(x * 100)}%`;
}

function main(argv) {
  const args = { top: 10 };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--threshold') args.threshold = parseFloat(argv[(i += 1)]);
    else if (argv[i] === '--min-complexity') args.minComplexity = parseInt(argv[(i += 1)], 10);
    else if (argv[i] === '--top') args.top = parseInt(argv[(i += 1)], 10);
  }

  const cfg = loadConfig();
  const threshold = args.threshold ?? cfg.threshold;
  const minComplexity = args.minComplexity ?? cfg.minComplexity;

  let coverage;
  try {
    coverage = JSON.parse(readFileSync(COVERAGE_JSON, 'utf-8'));
  } catch {
    console.error(
      `${COVERAGE_JSON} not found — run \`npm test\` first ` +
        '(this gate reads the coverage vitest writes).',
    );
    return 2;
  }

  const files = sourceTsFiles(JS_DIR);
  const complexity = complexityByFile(files);
  const scores = collectScores(complexity, coverage);
  scores.sort((a, b) => b.crap - a.crap);

  const rel = (p) => p.slice(REPO_ROOT.length + 1);
  if (args.top && scores.length) {
    console.log(`Top ${Math.min(args.top, scores.length)} riskiest functions:`);
    for (const s of scores.slice(0, args.top)) {
      console.log(
        `  ${rel(s.path)}:${s.line} ${s.name} ` +
          `(CRAP=${s.crap.toFixed(1)}, CC=${s.cc}, cov=${pct(s.cov)})`,
      );
    }
  }

  const offenders = scores.filter((s) => s.cc > minComplexity && s.crap > threshold);
  if (offenders.length) {
    console.log(
      `\nFAIL: ${offenders.length} function(s) exceed CRAP ${threshold} with CC > ${minComplexity}:`,
    );
    for (const s of offenders) {
      console.log(
        `  ${rel(s.path)}:${s.line} ${s.name} ` +
          `(CRAP=${s.crap.toFixed(1)}, CC=${s.cc}, cov=${pct(s.cov)})`,
      );
    }
    console.log('Add tests or reduce complexity to bring these down.');
    return 1;
  }

  console.log(`\nOK: no function exceeds CRAP ${threshold} (with CC > ${minComplexity}).`);
  return 0;
}

process.exit(main(process.argv.slice(2)));
