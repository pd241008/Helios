#!/usr/bin/env python3
"""Verify SHA-256 manifests shipped with the Helios artifact.

Checks:
  1. manifest/checkpoint_sha256.txt   — shipped model checkpoints
  2. manifest/dataset_sha256.txt      — regenerable dataset provenance (optional)

Exit code 0 = PASS, 1 = FAIL (missing/corrupt files).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def verify(manifest_path: Path) -> tuple[int, int]:
    if not manifest_path.exists():
        print(f"  SKIP {manifest_path.name} (not present)")
        return 0, 0

    ok = bad = 0
    for line in manifest_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        expected, rel = line.split(maxsplit=1)
        rel = rel.lstrip("./")
        target = ROOT / rel
        if not target.exists():
            print(f"  FAIL missing: {rel}")
            bad += 1
            continue
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest == expected:
            ok += 1
        else:
            print(f"  FAIL hash mismatch: {rel}")
            bad += 1
    name = manifest_path.name
    print(f"  {name}: {ok} ok, {bad} failed")
    return ok, bad


def main() -> int:
    print("Helios artifact manifest verification")
    ok1, bad1 = verify(ROOT / "manifest" / "checkpoint_sha256.txt")
    ok2, bad2 = verify(ROOT / "manifest" / "dataset_sha256.txt")
    total, failed = ok1 + ok2, bad1 + bad2
    if failed:
        print(f"verify_manifest: FAIL ({failed}/{total} entries)")
        return 1
    print(f"verify_manifest: PASS ({total}/{total} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
