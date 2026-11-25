#!/bin/sh
# verify_digests.sh — verify every file in SHA256SUMS against its
# recorded SHA-256. Exit 0 only if every check passes.
set -eu
cd "$(dirname "$0")/.."
sha256sum -c SHA256SUMS
