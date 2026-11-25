#!/usr/bin/env python3
"""make_reproduction_transcript.py — fresh-clone reproduction transcript.

Usage: python3 scripts/make_reproduction_transcript.py

Copies the pack to a fresh directory, runs the documented reproduction
there (`bash scripts/run_all.sh`, then `bash scripts/verify_digests.sh`),
diffs the regenerated outputs against the committed ones, and writes
the full captured output to outputs/fresh-clone-reproduction.log.

The transcript uses the stable relative label "fresh-clone" for the
copy directory — never an absolute path — so the file is identical
wherever the pack is cloned. After writing the transcript, regenerate
SHA256SUMS (the transcript is covered by it) and re-run
verify_digests.sh; the transcript's own verify output covers the state
before the transcript was added, which the transcript header states.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

CLONE_LABEL = "fresh-clone"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmp = tempfile.mkdtemp(prefix="pruning-repro-")
    clone = os.path.join(tmp, CLONE_LABEL)
    try:
        shutil.copytree(
            base, clone,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc",
                os.path.join("outputs", "run_all.log"),
                os.path.join("outputs", "fresh-clone-reproduction.log")))
        lines = []
        lines.append("Fresh-clone reproduction transcript")
        lines.append("Pack: postfiatd-ledger-pruning-availability-"
                     "assessment")
        lines.append("Clone directory (relative label): %s" % CLONE_LABEL)
        lines.append("Reproduction commands (from README):")
        lines.append("  bash scripts/run_all.sh")
        lines.append("  bash scripts/verify_digests.sh")
        lines.append("Note: this transcript records the reproduction of "
                     "the pack state before the transcript itself was "
                     "added. The clone's verify_digests.sh run below "
                     "covers that state; the final pack's "
                     "verify_digests.sh (run after the transcript was "
                     "added and SHA256SUMS regenerated) covers the "
                     "transcript too. The manifest excludes itself, "
                     "SHA256SUMS, and outputs/run_all.log.")
        lines.append("")
        lines.append("=== bash scripts/run_all.sh ===")
        run = subprocess.run(
            ["bash", "scripts/run_all.sh"], cwd=clone,
            capture_output=True, text=True)
        lines.append(run.stdout)
        if run.stderr:
            lines.append("--- stderr ---")
            lines.append(run.stderr)
        lines.append("exit status: %d" % run.returncode)
        lines.append("")
        lines.append("=== outputs/run_all.log from the fresh-clone run "
                     "===")
        run_log = os.path.join(clone, "outputs", "run_all.log")
        with open(run_log, "r", encoding="utf-8") as f:
            lines.append(f.read())
        lines.append("--- end of run_all.log ---")
        lines.append("")
        lines.append("=== bash scripts/verify_digests.sh ===")
        ver = subprocess.run(
            ["bash", "scripts/verify_digests.sh"], cwd=clone,
            capture_output=True, text=True)
        lines.append(ver.stdout)
        if ver.stderr:
            lines.append("--- stderr ---")
            lines.append(ver.stderr)
        lines.append("exit status: %d" % ver.returncode)
        lines.append("")
        lines.append("=== diff of regenerated outputs vs committed "
                     "outputs ===")
        lines.append("(excludes outputs/run_all.log and this transcript, "
                     "which did not exist in the clone)")
        diff = subprocess.run(
            ["diff", "-r", "--exclude=run_all.log",
             "--exclude=fresh-clone-reproduction.log",
             os.path.join(clone, "outputs"),
             os.path.join(base, "outputs")],
            capture_output=True, text=True)
        if diff.stdout:
            lines.append(diff.stdout)
        else:
            lines.append("identical")
        lines.append("diff exit status: %d" % diff.returncode)
        lines.append("")
        lines.append("=== manifest.json SHA-256 (committed copy) ===")
        lines.append(sha256_file(os.path.join(base, "manifest.json")))
        lines.append("=== end of output ===")
        out_path = os.path.join(base, "outputs",
                                "fresh-clone-reproduction.log")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print("wrote %s (run_all exit %d, verify exit %d, diff exit %d)"
              % (out_path, run.returncode, ver.returncode,
                 diff.returncode))
        return 0 if (run.returncode == 0 and ver.returncode == 0
                     and diff.returncode == 0) else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
