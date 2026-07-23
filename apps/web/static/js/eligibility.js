// eligibility.js — the ONE shared eligibility rule.
//
// `eligForAccess(access, gender, age)` maps a session's access type + the viewer's
// gender/age to the UI's three-way badge state: 'in' (✓), 'chk' (?), 'no' (✕).
// It mirrors the Python domain's `eligibility()` rule (src/swimzh/domain/access.py)
// but folds "not yet determinable" (missing gender/age) into a DISTINCT 'chk' — the
// UI's ? — instead of a bare False, so that ? is NEVER merged with ✕.
//
// This exact module is imported by the board row badge (S2), the detail panel (S3),
// and the toolbar (S4): one rule, one place. Pure — no DOM, no canvas.
//
// `access` is the domain access class name as `/swim` emits it
// (`type(session.access).__name__`): PublicSwim | LaneSwim | FamilyTime | WomenOnly
// | SeniorsOnly | SchoolReserved | ClubReserved | AdultsOnly.

// The three badge states. Exported so callers name them, never string-literal-drift.
export const ELIG_IN = 'in';
export const ELIG_CHK = 'chk';
export const ELIG_NO = 'no';

// Domain defaults (access.py): SeniorsOnly.min_age=60, AdultsOnly.min_age=18. The
// `/swim` access field carries only the class name, so the thresholds live here.
const SENIORS_MIN_AGE = 60;
const ADULTS_MIN_AGE = 18;

// Access types anyone may attend → always ✓.
const OPEN_TO_ALL = new Set(['PublicSwim', 'LaneSwim', 'FamilyTime']);
// Access types never open to the public → always ✕ (mirrors the domain's False).
const NEVER_PUBLIC = new Set(['SchoolReserved', 'ClubReserved']);

function ageKnown(age) {
  return typeof age === 'number' && Number.isFinite(age);
}

function womenOnly(gender) {
  // female → ✓, male → ✕. Unset gender and 'diverse' are NOT a hard no: they need a
  // human check with the venue, so they map to ? (never merged with ✕).
  if (gender === 'female') return ELIG_IN;
  if (gender === 'male') return ELIG_NO;
  return ELIG_CHK; // '' | null | undefined | 'diverse'
}

function minAge(age, threshold) {
  if (!ageKnown(age)) return ELIG_CHK; // age unknown → ? (need the age to decide)
  return age >= threshold ? ELIG_IN : ELIG_NO;
}

/**
 * eligForAccess(access, gender, age) → 'in' | 'chk' | 'no'.
 * @param {string} access domain access class name (see module header).
 * @param {string} gender '' | 'female' | 'male' | 'diverse' (missing ⇒ unset).
 * @param {number|null} age viewer age, or null/undefined if unknown.
 */
export function eligForAccess(access, gender = '', age = null) {
  if (OPEN_TO_ALL.has(access)) return ELIG_IN;
  if (NEVER_PUBLIC.has(access)) return ELIG_NO;
  if (access === 'WomenOnly') return womenOnly(gender);
  if (access === 'SeniorsOnly') return minAge(age, SENIORS_MIN_AGE);
  if (access === 'AdultsOnly') return minAge(age, ADULTS_MIN_AGE);
  // Unknown / new access type: default to open rather than inventing a restriction.
  return ELIG_IN;
}

/**
 * dayEligibility(states) → the single badge for a whole row (a pool's day, or a
 * day in the week). Reduces the row's per-session states with the priority
 * in > chk > no, so a row that has ANY attendable session is ✓, a row with only
 * "check" sessions is ? (crucially NOT ✕), and only an all-✕ row is ✕.
 * @param {Array<'in'|'chk'|'no'>} states
 */
export function dayEligibility(states) {
  if (states.some((s) => s === ELIG_IN)) return ELIG_IN;
  if (states.some((s) => s === ELIG_CHK)) return ELIG_CHK;
  return ELIG_NO; // all ✕, or no sessions at all
}
