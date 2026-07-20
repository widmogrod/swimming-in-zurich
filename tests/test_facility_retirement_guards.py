"""Plan B (retire-facility-table) invariant guards — falsifiable, grep/AST/schema based.

Plan B collapsed the composed schedule blob to ONE place (``pool.facility_doc``) behind ONE
``PoolId``-typed write door (``write_schedules``) and made ``curation_status`` a read-time
derivation. Plan C then physically deleted the legacy ``facility`` table (with ``build-gold``,
its last writer, gone). So these guards lock the *read* and *single-writer* invariants AND now
assert the table is gone — no runtime source creates, reads, or writes a ``facility`` table.

Each guard is falsifiable: it fires on a real violation (verified by a temporary mutation during
implementation) and its companion positive assertion proves it is scanning live source rather
than passing vacuously.

Mirrors the existing grep-guard patterns in ``tests/test_layering.py`` and
``apps/web/tests/api/test_single_source_of_truth.py``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src" / "swimzh"
_APP = _ROOT / "apps" / "web"
_SQLITE_REPO = _SRC / "storage" / "sqlite_repo.py"


def _runtime_files() -> list[Path]:
    """Every runtime ``.py`` under ``src/swimzh/**`` and ``apps/web/**`` — tests excluded."""
    files: list[Path] = []
    for root in (_SRC, _APP):
        files += [p for p in root.rglob("*.py") if "tests" not in p.parts]
    return files


def _matching_lines(path: Path, pattern: re.Pattern[str]) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if pattern.search(ln)]


# --- Guard 1: no runtime READ of the `facility` table -----------------------------------------

# `facility` in FROM/JOIN position only. `\bfacility\b` has no word boundary before `_`, so
# `facility_doc` / `facility_id` (the pool-column blob / identity) never match — only the bare
# table name in a read does. `INTO facility` (a write, now also gone) is not FROM/JOIN.
_READS_FACILITY = re.compile(r"\b(?:FROM|JOIN)\s+facility\b", re.IGNORECASE)


def test_no_runtime_read_of_facility_table() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _runtime_files():
        hits = _matching_lines(path, _READS_FACILITY)
        if hits:
            offenders[str(path.relative_to(_ROOT))] = hits
    assert not offenders, (
        "runtime source must not READ the `facility` table (the read path is `pool.facility_doc`); "
        f"Plan C deleted the table entirely: {offenders}"
    )


def test_reads_facility_matcher_fires_on_a_read_but_not_on_columns() -> None:
    # Proves the matcher is live and precise (falsifiable, not vacuous): it catches a real
    # `FROM facility` read yet ignores the `facility_doc`/`facility_id` column names it must not
    # confuse for the table, and ignores an `INSERT INTO facility` write (a write, not a read).
    assert _READS_FACILITY.search("SELECT doc FROM facility ORDER BY facility_id")
    assert _READS_FACILITY.search("JOIN facility f ON f.facility_id = pool.id")
    assert not _READS_FACILITY.search("SELECT facility_doc FROM pool WHERE facility_doc NOT NULL")
    assert not _READS_FACILITY.search("INSERT OR REPLACE INTO facility (facility_id, doc)")


# --- Guard 2: `write_schedules` is the ONLY writer of `pool.facility_doc` ----------------------

# A write to the blob column: `UPDATE pool SET facility_doc = ...`, or an `INSERT INTO pool`
# whose column list names facility_doc. Reads (`SELECT ... facility_doc`, `WHERE facility_doc
# IS NOT NULL`) are not writes and must not match.
_SET_FACILITY_DOC = re.compile(r"\bSET\s+facility_doc\b", re.IGNORECASE)
_INSERT_POOL_FACILITY_DOC = re.compile(
    r"INSERT\s+INTO\s+pool\b[\s\S]*?\bfacility_doc\b", re.IGNORECASE
)

_SOLE_FACILITY_DOC_WRITER = "write_schedules"


def _writes_facility_doc(source: str) -> bool:
    return bool(_SET_FACILITY_DOC.search(source) or _INSERT_POOL_FACILITY_DOC.search(source))


def _functions_writing_facility_doc(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    if not _writes_facility_doc(text):  # cheap skip: no blob write anywhere in the file
        return []
    names: list[str] = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            segment = ast.get_source_segment(text, node)
            if segment is not None and _writes_facility_doc(segment):
                names.append(node.name)
    return names


def test_only_write_schedules_writes_facility_doc() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _runtime_files():
        writers = _functions_writing_facility_doc(path)
        rogue = [name for name in writers if name != _SOLE_FACILITY_DOC_WRITER]
        if rogue:
            offenders[str(path.relative_to(_ROOT))] = rogue
    assert not offenders, (
        f"only `{_SOLE_FACILITY_DOC_WRITER}` may write `pool.facility_doc` "
        f"(single-writer seam): {offenders}"
    )


def test_write_schedules_is_actually_a_facility_doc_writer() -> None:
    # Positive half: the guard is scanning real source — `write_schedules` genuinely contains a
    # `pool.facility_doc` write, so the single-writer assertion above is not vacuously green.
    assert _SOLE_FACILITY_DOC_WRITER in _functions_writing_facility_doc(_SQLITE_REPO)


# --- Guard 3: no writable `curation_status` column (B3 derive-at-read is locked) ---------------

# Isolate the `pool` CREATE TABLE column list (ends `) STRICT`, unlike the `facility` table).
_POOL_TABLE = re.compile(r"CREATE\s+TABLE[^;(]*\bpool\b\s*\(([\s\S]*?)\)\s*STRICT", re.IGNORECASE)
# A write to a curation_status column (never `SELECT`/`WHERE` — there is nothing to derive-write).
_WRITES_CURATION_STATUS = re.compile(
    r"\bSET\s+curation_status\b|INSERT\s+INTO\s+pool\b[\s\S]*?\bcuration_status\b", re.IGNORECASE
)


def _pool_columns() -> str:
    match = _POOL_TABLE.search(_SQLITE_REPO.read_text(encoding="utf-8"))
    assert match is not None, "could not locate the `pool` CREATE TABLE in sqlite_repo.py"
    return match.group(1)


def test_pool_table_has_no_curation_status_column() -> None:
    assert "curation_status" not in _pool_columns(), (
        "`curation_status` must NOT be a stored `pool` column — it is derived at read via "
        "codec.is_curated (B3); a stored column can desync from the schedule it describes."
    )


def test_no_runtime_code_writes_curation_status() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _runtime_files():
        hits = _matching_lines(path, _WRITES_CURATION_STATUS)
        if hits:
            offenders[str(path.relative_to(_ROOT))] = hits
    assert not offenders, (
        f"no runtime code may WRITE a `curation_status` column (derive-at-read only): {offenders}"
    )


def test_pool_table_still_carries_facility_doc() -> None:
    # Positive half: the column extractor targets the real `pool` table (falsifiable, not
    # vacuous) — it still finds the `facility_doc` blob column the read path depends on.
    assert "facility_doc" in _pool_columns()


# --- Guard 4: the `facility` table is GONE (Plan C physical delete) ----------------------------

# A `CREATE TABLE ... facility (` — `[^;(]*` stays before the opening paren, so `\bfacility\b`
# there matches only a table NAMED facility, never the `facility_doc` column inside `pool`.
_CREATES_FACILITY_TABLE = re.compile(r"CREATE\s+TABLE[^;(]*\bfacility\b\s*\(", re.IGNORECASE)
# Any write targeting the table: `INSERT ... INTO facility`. `INTO facility_doc` is impossible
# (no such column write shape), and `\bfacility\b` won't match `facility_doc`/`facility_id`.
_WRITES_INTO_FACILITY = re.compile(r"\bINTO\s+facility\b", re.IGNORECASE)


def test_no_runtime_creates_or_writes_facility_table() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _runtime_files():
        hits = _matching_lines(path, _CREATES_FACILITY_TABLE) + _matching_lines(
            path, _WRITES_INTO_FACILITY
        )
        if hits:
            offenders[str(path.relative_to(_ROOT))] = hits
    assert not offenders, (
        "the `facility` table was deleted in Plan C; no runtime source may CREATE or WRITE it "
        f"(the schedule blob lives on `pool.facility_doc`): {offenders}"
    )


def test_facility_table_matchers_are_precise() -> None:
    # Falsifiable, not vacuous: the absence matchers fire on a real CREATE/INSERT of the table
    # yet ignore the `pool` table and its `facility_doc` column that legitimately remain.
    assert _CREATES_FACILITY_TABLE.search("CREATE TABLE IF NOT EXISTS facility (facility_id TEXT")
    assert not _CREATES_FACILITY_TABLE.search("CREATE TABLE IF NOT EXISTS pool (facility_doc TEXT")
    assert _WRITES_INTO_FACILITY.search("INSERT OR REPLACE INTO facility (facility_id, doc)")
    assert not _WRITES_INTO_FACILITY.search("INSERT INTO pool (id, facility_doc) VALUES (?, ?)")
