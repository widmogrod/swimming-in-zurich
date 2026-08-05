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
// | SeniorsOnly | SchoolReserved | ClubReserved | AdultsOnly | GirlsOnly |
// GenderDiverse | AccompaniedChildren.
//
// The mirror is CHECKED, not asserted in prose: `apps/web/tests/fixtures/eligibility_contract.json`
// is generated from the Python `eligibility()` itself (see
// `apps/web/tests/test_eligibility_ui_contract.py`) and replayed against this module by
// `eligibility.test.js`. A domain arm that changes shape fails on both sides.

// The three badge states. Exported so callers name them, never string-literal-drift.
export const ELIG_IN = 'in';
export const ELIG_CHK = 'chk';
export const ELIG_NO = 'no';

// Domain defaults (access.py): SeniorsOnly.min_age=60, AdultsOnly.min_age=18. The
// `/swim` access field carries only the class name, so the thresholds live here.
const SENIORS_MIN_AGE = 60;
const ADULTS_MIN_AGE = 18;
// GenderDiverse.min_age is REQUIRED in the domain (no default) but still does not cross
// the wire — `/swim` sends only the class name. Exactly one cell citywide produces this
// arm today and it publishes "ab 16 Jahren", which is why 16 is the mirrored value.
//
// THIS MIRROR IS UNGUARDED. The generated contract fixture pins only the representative
// instance hand-written in `REPRESENTATIVE_ACCESS` (access.py) — `GenderDiverse(min_age=16)`
// — never a bound actually parsed from a page. The scraper emits whatever the page
// publishes, so a page that starts saying "ab 14 Jahren" would leave BOTH QA chains green
// while this constant silently disagrees with the server: a 15-year-old would get the
// server's `gender_diverse_confirm` (?) but be drawn ✕ — a hard exclusion the domain never
// issued, the mirror image of the harm this module was fixed for.
//
// The honest guard is carrying `min_age` on the wire (an `OptionOut` field, so the browser
// decides from the session's own bound instead of a constant); that is an API change and
// out of this slice's scope. The same caveat applies to the two thresholds above.
const GENDER_DIVERSE_MIN_AGE = 16;

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

function girlsOnly(gender) {
  // A *"für Mädchen"* session. Mirrors `_girls_only` (access.py): only the EXCLUSION is
  // decidable. A woman is NOT welcomed — the city publishes no age cutoff for "Mädchen",
  // so she is ? (check with the pool), the same shape as the women-only confirm.
  if (gender === 'male' || gender === 'diverse') return ELIG_NO;
  return ELIG_CHK; // 'female' | '' | null | undefined
}

function genderDiverse(age) {
  // *"offen für trans und nicht-binäre Personen ab N Jahren"*. Mirrors `_gender_diverse`:
  // NEVER a hard deny on gender — being trans is not a value of the gender filter (a trans
  // woman's gender is female), so deciding this from it would wrongly exclude her. The
  // published age is the one checkable fact, and above it the answer is ? not ✓.
  if (ageKnown(age) && age < GENDER_DIVERSE_MIN_AGE) return ELIG_NO;
  return ELIG_CHK;
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
  if (access === 'GirlsOnly') return girlsOnly(gender);
  if (access === 'GenderDiverse') return genderDiverse(age);
  // Accompaniment is not an attribute the filter carries, so this is never decidable
  // either way — ? (check with the pool), never ✓ and never ✕.
  if (access === 'AccompaniedChildren') return ELIG_CHK;
  // Unknown / new access type → ? , never ✓.
  //
  // This used to "default to open rather than inventing a restriction", which is how an
  // adult man got a ✓ on a girls-only session the server had already refused: the fallback
  // asserted "you may attend" about a rule this module had never heard of. ? asserts
  // nothing — it says *check with the pool*, which is the only honest answer for a
  // restriction we cannot read. It is also the state the UI never merges with ✕.
  return ELIG_CHK;
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
