"""Run a dump function against a PAST commit's source tree.

Why this exists
---------------
Two of the lane-stack-board fixtures — `swim_baseline_2026-08-12.json` (S1) and
`swim_lane_fields_pre_s2.json` (S2) — are **frozen pre-change references**. Their entire
evidential value is that they were produced by code that did not yet contain the change
they now guard. A test compares today's output against them; if they were ever regenerated
from today's tree, the comparison would become "the code agrees with itself" and would pass
no matter what broke.

So these generators exist for AUDIT, not for convenience. They must be able to answer "where
did this number come from?" — and the only honest answer is "from commit <sha>, which is
still in this repository, and here is the command that replays it".

Hence: no generator here regenerates in place from the working tree. Each one checks out an
explicit historical commit with `git archive`, imports the code FROM THAT TREE, and dumps.
Byte-identical output is the expected result and the point; a difference means either the
commit is wrong or history was rewritten, and either way a human must look.

How the sandbox works
---------------------
`git archive <commit> | tar -x` into a temp dir, then run the caller's dumper in a CHILD
interpreter whose `PYTHONPATH` puts that tree's `src/` and root ahead of everything else, and
whose cwd is that tree (the pipeline resolves `data/` relatively). Third-party packages still
come from the current virtualenv — deliberately: these commits are a handful apart with one
unchanged lockfile, so the only thing we want to travel back in time is OUR source.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "apps" / "web" / "tests" / "fixtures"


def resolve_commit(commit: str) -> str:
    """The full sha of `commit`, failing loudly if this checkout does not have it."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--verify", f"{commit}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"commit {commit!r} is not in this repository — a frozen fixture cannot be "
            f"regenerated without the tree that produced it.\n{result.stderr.strip()}"
        )
    return result.stdout.strip()


def dump_at_commit(commit: str, module: str) -> Any:
    """Run `<module>.dump()` against `commit`'s source tree and return its JSON result.

    `module` is a dotted path under `scripts.fixtures`; this whole package is copied into
    the sandbox first, so the generator that runs there is the one you are reading, while
    every `swimzh` / `apps` / `tests` import it makes resolves to the archived tree.
    """
    sha = resolve_commit(commit)
    with tempfile.TemporaryDirectory(prefix="swimzh-frozen-") as tmp:
        tree = Path(tmp) / "tree"
        tree.mkdir()
        _extract(sha, tree)
        # The generators themselves come from TODAY's tree — only the code they MEASURE is
        # historical. (At `commit` these files did not exist at all.)
        staged = tree / "scripts" / "fixtures"
        shutil.rmtree(staged, ignore_errors=True)
        shutil.copytree(Path(__file__).resolve().parent, staged)
        return _run(tree, module)


def _extract(sha: str, into: Path) -> None:
    archive = into.parent / "tree.tar"
    with archive.open("wb") as handle:
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "archive", sha],
            stdout=handle,
            check=True,
        )
    with tarfile.open(archive) as tar:
        tar.extractall(into, filter="data")
    archive.unlink()


def _run(tree: Path, module: str) -> Any:
    # The dump goes to a FILE, not stdout: the atomic build narrates its phases on stdout and
    # would otherwise be parsed as part of the JSON.
    out = tree.parent / "dump.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(tree), str(tree / "src")])
    # A stray developer .env must not reach a fixture that is meant to be reproducible.
    env.pop("SWIMZH_GOLD_DB", None)
    env["SWIMZH_CACHE"] = "off"
    result = subprocess.run(
        [sys.executable, "-c", _CHILD, module, str(out)],
        cwd=tree,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            "the dump failed inside the archived tree:\n"
            f"{result.stdout.strip()}\n{result.stderr.strip()}"
        )
    return json.loads(out.read_text(encoding="utf-8"))


# Imports the caller's module inside the sandbox and writes its `dump()` as JSON. Kept to one
# string so the sandbox needs no files of its own beyond the archive + this package.
_CHILD = (
    "import importlib, json, pathlib, sys\n"
    "payload = importlib.import_module(sys.argv[1]).dump()\n"
    "pathlib.Path(sys.argv[2]).write_text(json.dumps(payload), encoding='utf-8')\n"
)


def write_frozen(path: Path, payload: Any, *, force: bool, check: bool) -> int:
    """Write `payload` to `path`, refusing to clobber a committed frozen fixture.

    Default behaviour is `--check`-like on purpose: overwriting is the dangerous operation
    here, so it takes an explicit `--force` and prints what changed first.
    """
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if not path.exists():
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path} (did not exist)")
        return 0

    current = json.loads(path.read_text(encoding="utf-8"))
    if current == payload:
        print(f"{path.name}: reproduced EXACTLY from the frozen commit.")
        return 0

    print(
        f"{path.name}: the replay DIFFERS from the committed fixture.\n"
        "  This is not a routine refresh. A frozen reference only differs if the commit is "
        "wrong, history was rewritten, or a committed input the replay reads has changed.\n"
        "  Investigate before writing; a fixture rewritten to match today's code proves nothing."
    )
    for line in _differences(current, payload):
        print(f"    {line}")
    if check:
        return 1
    if not force:
        print("  Refusing to overwrite. Pass --force if you have established WHY it moved.")
        return 1
    path.write_text(text, encoding="utf-8")
    print(f"  --force given: {path} overwritten.")
    return 0


def _differences(before: Any, after: Any, path: str = "$", limit: int = 20) -> list[str]:
    """The paths at which two JSON documents disagree — so a diff names WHAT moved.

    A frozen fixture that drifts is an investigation, and an investigation starts with
    "which field", not "something changed".
    """
    if type(before) is not type(after):
        return [f"{path}: {type(before).__name__} -> {type(after).__name__}"]
    out: list[str] = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            if key not in before:
                out.append(f"{path}.{key}: added")
            elif key not in after:
                out.append(f"{path}.{key}: removed")
            else:
                out.extend(_differences(before[key], after[key], f"{path}.{key}"))
            if len(out) >= limit:
                return out[:limit]
        return out
    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            return [f"{path}: {len(before)} entries -> {len(after)}"]
        for index, (b, a) in enumerate(zip(before, after, strict=True)):
            out.extend(_differences(b, a, f"{path}[{index}]"))
            if len(out) >= limit:
                return out[:limit]
        return out
    return [] if before == after else [f"{path}: {before!r} -> {after!r}"]
