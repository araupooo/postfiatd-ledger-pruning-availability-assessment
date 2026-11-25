#!/usr/bin/env python3
"""make_manifest.py — build manifest.json listing every pack file with
its size and SHA-256.

Usage: python3 scripts/make_manifest.py

Excluded from the manifest (self-reference avoidance):
  manifest.json itself, SHA256SUMS (which lists the manifest), the
  transient outputs/run_all.log, and the reproduction transcript
  outputs/fresh-clone-reproduction.log. The transcript is excluded
  because it records the manifest's SHA-256: including it would make
  the recorded SHA stale the moment the manifest is regenerated.
  The transcript is still a committed file and verify_digests.sh
  covers it through SHA256SUMS.

Deterministic: sorted paths, fixed JSON formatting.
"""

import hashlib
import json
import os

EXCLUDE = {"manifest.json", "SHA256SUMS",
           os.path.join("outputs", "run_all.log"),
           os.path.join("outputs", "fresh-clone-reproduction.log")}


def main():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    entries = []
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            path = os.path.join(root, name)
            rel = os.path.relpath(path, base)
            if rel in EXCLUDE or name.endswith(".pyc"):
                continue
            with open(path, "rb") as f:
                data = f.read()
            entries.append({
                "path": rel,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            })
    entries.sort(key=lambda e: e["path"])
    with open(os.path.join(base, "manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump({"files": entries}, f, indent=2, sort_keys=True)
        f.write("\n")
    print("manifest.json: %d files" % len(entries))


if __name__ == "__main__":
    main()
