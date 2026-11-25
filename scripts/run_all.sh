#!/bin/sh
# run_all.sh — full reproduction: run every scenario, build the matrix
# and the control table, rebuild the manifest and the digests, then
# verify the digests. Exit 0 only if every step passes.
#
# Outputs are deterministic: no wall clock, no random module, no
# absolute paths in any generated file. The run log itself
# (outputs/run_all.log) is excluded from SHA256SUMS and from the
# manifest as a run artifact.
set -eu
cd "$(dirname "$0")/.."
export PYTHONDONTWRITEBYTECODE=1
mkdir -p outputs
exec > outputs/run_all.log 2>&1
echo "run_all.sh: starting"
for f in scenarios/S*.json; do
    python3 scripts/load_harness.py "$f"
done
python3 scripts/build_matrix.py
python3 scripts/measure_controls.py
python3 scripts/make_manifest.py
bash scripts/make_sha256sums.sh
bash scripts/verify_digests.sh
echo "run_all.sh: OK"
