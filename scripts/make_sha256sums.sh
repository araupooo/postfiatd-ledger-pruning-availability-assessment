#!/bin/sh
# make_sha256sums.sh — regenerate SHA256SUMS over every pack file
# except SHA256SUMS itself and the transient outputs/run_all.log
# (which carries no wall-clock line by design, but is excluded as a
# run artifact like in the earlier packs).
#
# Run from the pack root. Output is sorted and deterministic.
set -eu
cd "$(dirname "$0")/.."
find . -type f \
    ! -path '*/__pycache__/*' \
    ! -name '*.pyc' \
    ! -name 'SHA256SUMS' \
    ! -path './outputs/run_all.log' \
    -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
wc -l < SHA256SUMS | xargs echo "SHA256SUMS entries:"
