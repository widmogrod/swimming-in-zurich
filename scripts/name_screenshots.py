"""Give exported xcresult attachments the names their test chose.

`xcrun xcresulttool export attachments` writes one file per attachment named after its UUID and
records the intended name in `manifest.json`. For a screenshot set that ordering matters twice
over: the App Store shows screenshots in upload order, and a reviewer of this repo has to be
able to tell `01-find` from `05-map` without opening both.

The suggested name carries a per-run suffix (`01-find_0_<uuid>.png`), which would defeat the
point — a set that changes filename every run cannot be diffed, and re-uploading it looks like
five new screenshots rather than five corrected ones. So the suffix is stripped and the stable
prefix kept.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# "01-find_0_41AB3819-...png" -> "01-find.png". The suffix is the attachment's payload index
# plus its UUID; both change on every run and neither identifies the screen.
SUFFIX = re.compile(r"_\d+_[0-9A-Fa-f-]{36}(?=\.\w+$)")


def main(directory: Path) -> int:
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        print(f"no manifest.json in {directory} — nothing was exported", file=sys.stderr)
        return 1

    renamed = 0
    for entry in json.loads(manifest_path.read_text()):
        for attachment in entry.get("attachments", []):
            exported = attachment.get("exportedFileName")
            suggested = attachment.get("suggestedHumanReadableName")
            if not exported or not suggested:
                continue
            source = directory / exported
            if not source.exists():
                continue
            source.replace(directory / SUFFIX.sub("", suggested))
            renamed += 1

    manifest_path.unlink()
    print(f"named {renamed} screenshot(s) in {directory}:")
    for shot in sorted(directory.iterdir()):
        print(f"  {shot.name}")
    return 0 if renamed else 1


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "dist/screenshots")))
