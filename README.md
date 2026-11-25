# Postfiatd Ledger Pruning and Historical Data Availability Assessment

Pinned postfiatd commit: `0085a1ff885d6a446369cf73a4430f75af22be55`
(2026-10-10). All 22 cited source files were verified blob-by-blob
against the GitHub API tree for that commit (22/22 agree); line
numbers were read on the local checkout, never from a raw-file fetch.
See `docs/source-inventory.md`.

## How to reproduce

```sh
bash scripts/run_all.sh
bash scripts/verify_digests.sh
```

`run_all.sh` reruns every scenario, rebuilds the matrix and the
control table, regenerates the manifest and the digests, and verifies
them (exit 0 only if every step passes). `verify_digests.sh` checks
every file in `SHA256SUMS` against its recorded SHA-256.

**Fresh-clone reproduction transcript:
`outputs/fresh-clone-reproduction.log`.** It records a full
reproduction from a fresh copy of this pack — the commands above, the
complete `verify_digests.sh` output with its exit status, and a diff
of the regenerated outputs against the committed ones. The transcript
was produced by `scripts/make_reproduction_transcript.py` (run it to
regenerate: `python3 scripts/make_reproduction_transcript.py`, then
regenerate `SHA256SUMS` with `bash scripts/make_sha256sums.sh`).

## What this pack shows

When postfiatd pruning, partial history, and state sync prevent
operators or auditors from retrieving historical ledgers. A faithful
protocol-level simulator (`scripts/simulator.py`) re-implements the
pinned pruning / retention / fetch / sync logic; 11 scenarios
(`scenarios/`) measure it. **Every measured number in this pack is
SIMULATED** — the parameters, gates, and thresholds are the pinned
code's; the ledger contents, peer latencies, and node failures are
deterministic stand-ins. No live postfiatd node was run (see
`docs/environment.md`, L1). OBSERVED means read directly from the
pinned source; SIMULATED means produced by the simulator;
UNMEASURED means code-verified only (controls C16, C17).

Headline results (full matrix in `outputs/matrix.json` / `.csv`):

| Scenario | Severity | Measured result |
|----------|----------|-----------------|
| S0 baseline full-history | INFO | 120/120 RPC fetches served locally, 0 acquires |
| S1 aggressive pruning (online_delete 256, 600 ledgers) | LOW | 2 rotations, 1,255 rows deleted in 13 batches; 8/8 RPC fetches served via a full peer |
| S2 pruned-range fetch, no full peer | HIGH | 7/7 pruned-range requests `lgrNotFound`; 4 first attempts × 7 timeouts (21 s each); 84,000 ms wasted; 3/3 in-window served |
| S3 partial-history node | MEDIUM | Backfill 0 acquired (halt at 1743, gate-refused); RPC 15/15 served via 17 acquires |
| S4 backfill from a pruned peer | MEDIUM | 742 acquired; floor ledger 1257 failed after 7 timeouts (21 s); validated range [1258, 2000] |
| S5 backfill with a full-history second peer | LOW | 743 acquired; halt at 1256 (gate-refused); the floor, not the peer, binds |
| S6 can_delete advisory | LOW | never → 0 rotations; hash 1200 → 1; now → 1 more; always → 2 more; 4 rotations, 1,900 rows, 20 batches |
| S7 LedgerCleaner repair | MEDIUM | 3/4 cleaned; ledger 1000 dropped (no peer holds it); validated range [1001, 2000] |
| S8 RPC resolution matrix | LOW | Index at age 121 s → `rpcNOT_SYNCED`; hash at 121 s → served; both fields → parameter error; index 2000 → too large; index 0 → too small |
| S9 fetch-depth clamp | MEDIUM | Default clamp 256 → earliest fetch 1744; fetch_depth 100 → clamp 100 → earliest fetch 1900; 5 fetch packs served, 4 refused |
| S10 rotation deferred while stale | LOW | 0 rotations across 300 stale + 10 syncing ledgers; 2 rotations after recovery; 1,310 rows in 14 batches |

Key finding: the background backfill cannot extend history below the
SQL minimum without an online-delete floor (S3: 0 acquired), and with
a floor it stops at the floor (S5). A full peer makes pruning
invisible to RPC (S1: 8/8 served); without one, pruned history is
unrecoverable (S2: 7/7 `lgrNotFound`). See `docs/findings-report.md`
and `docs/decision-memo.md`.

## Layout

- `scenarios/` — 11 scenario definitions (config, peers, initial
  state, steps, severity, reasoning). Each is the input to the
  harness, not a report.
- `scripts/` — `simulator.py` (the protocol model),
  `load_harness.py` (runs one scenario),
  `build_matrix.py` (severity-ranked matrix),
  `measure_controls.py` (control-effectiveness table),
  `make_manifest.py`, `make_sha256sums.sh`,
  `verify_digests.sh`, `run_all.sh` (full pipeline),
  `make_reproduction_transcript.py` (fresh-copy reproduction).
- `outputs/` — unedited per-scenario `.json` / `.csv` / `.log`,
  `matrix.json` / `.csv`, `controls.json` / `.csv`,
  `fresh-clone-reproduction.log`.
- `docs/` — `source-inventory.md` (22 cited files, blob SHAs, line
  spans), `environment.md` (model, fidelity, limitations),
  `methodology.md` (method, labels, model bugs found and fixed),
  `findings-report.md` (F1–F13), `control-inventory.md` (C00–C18),
  `remediation-report.md` (R1–R8), `decision-memo.md`.
- `manifest.json`, `SHA256SUMS` — file inventory with sizes and
  SHA-256; the manifest excludes itself, `SHA256SUMS`, and the
  transient `outputs/run_all.log`.

## Claim-to-evidence index

Every measured claim, its script, its raw output, and its primary
source. "Script" is the code that produced the number; "output" is
the unedited file carrying it; "source" is the pinned code the
behaviour copies.

| Claim | Script | Raw output | Primary source |
|---|---|---|---|
| Defaults LEDGER_HISTORY 256, FETCH_DEPTH 1,000,000,000 | `scripts/simulator.py` (config) | `scenarios/S0-*.json` (`config`) | `src/xrpld/core/Config.h:224-225` |
| `[ledger_history]` / `[fetch_depth]` parsing (full → max, none → 0, min depth 10) | `scripts/simulator.py` (config) | `scenarios/*.json` (`config`) | `src/xrpld/core/detail/Config.cpp:652-673` |
| S1: 2 rotations, 1,255 rows, 13 batches; 8/8 RPC served | `scripts/load_harness.py` + `scripts/simulator.py` | `outputs/S1-aggressive-pruning.json` (steps, counters), `.csv`, `.log` | `SHAMapStoreImp.cpp:331-332, 550-600`; `LedgerMaster.cpp:75-99` |
| S1: re-acquired ledgers below minimumOnline do not extend the validated range | `scripts/load_harness.py` | `outputs/S1-aggressive-pruning.json` (`final.complete_ledgers`, `final.validated_range`) | `LedgerMaster.cpp:569-620, 1615-1620` |
| S2: 7/7 pruned-range `lgrNotFound`; 28 timeouts; 84,000 ms | `scripts/load_harness.py` | `outputs/S2-pruned-range-fetch-no-full-peer.json` (steps, rows, counters) | `InboundLedger.cpp:43-74, 376-390`; `TimeoutCounter.cpp:95-112`; `View.h:506-524` |
| S2: 4 candidate-step failures (reference 1024), 2 target failures via held candidate 1280, 1 direct hash failure | `scripts/measure_controls.py` (C05) | `outputs/controls.json` (C05); `outputs/S2-*.csv` | `LedgerMaster.cpp:1663-1730`; `View.h:517-524` |
| S3: backfill 0 acquired, halt 1743 gate-refused | `scripts/load_harness.py` | `outputs/S3-partial-history-node.json` (steps, events) | `LedgerMaster.cpp:75-99, 1945-1998`; `SHAMapStoreImp.cpp:711-720` |
| S3: RPC 15/15 served via 17 acquires, 7,808 ms | `scripts/load_harness.py` | `outputs/S3-partial-history-node.json` (steps, counters) | `RPCHelpers.cpp:1030-1145` |
| S4: 742 acquired; floor ledger 1257 failed after 7 timeouts | `scripts/load_harness.py` | `outputs/S4-backfill-from-pruned-peer.json` (steps, events, counters) | `LedgerMaster.cpp:75-99, 1825-1915`; `SHAMapStoreImp.cpp:711-720` |
| S4: fetch-pack prefetch invoked once, requested 0 ledgers | `scripts/load_harness.py` | `outputs/S4-backfill-from-pruned-peer.json` (counters: `fetch_packs_requested` 1; `.log`: "fetchForHistory want fetch pack 1257") | `LedgerMaster.cpp:1825-1915` |
| S5: 743 acquired; halt 1256 gate-refused | `scripts/load_harness.py` | `outputs/S5-backfill-with-full-peer.json` (steps, events) | `LedgerMaster.cpp:75-99`; `SHAMapStoreImp.cpp:711-720` |
| S6: never 0 rotations; hash 1200 → 1; now → 1 more; always → 2 more | `scripts/load_harness.py` | `outputs/S6-can-delete-advisory.json` (steps, events) | `CanDelete.cpp:37, 61-85`; `SHAMapStoreImp.cpp:331-332` |
| S6: rotation sets lastRotated to the current tip (1301, 1601, 1901, 2157) | `scripts/load_harness.py` | `outputs/S6-can-delete-advisory.json` (events: `rotate`) | `SHAMapStoreImp.cpp:331-344` |
| S7: 3/4 cleaned; 1000 dropped; validated range [1001, 2000] | `scripts/load_harness.py` | `outputs/S7-ledger-cleaner-repair.json` (steps, final) | `LedgerCleaner.cpp:272-330` |
| S8: index at 121 s → rpcNOT_SYNCED; hash → served; v1 → rpcNO_CURRENT; bounds errors | `scripts/load_harness.py` | `outputs/S8-rpc-resolution-matrix.json` (steps, rows) | `RPCHelpers.cpp:1030-1145`; `rpc/detail/Tuning.h:65` |
| S9: clamp 256 → earliest 1744; clamp 100 → earliest 1900; 5 served / 4 refused | `scripts/load_harness.py` | `outputs/S9-fetch-depth-clamp.json` (steps, counters) | `SHAMapStoreImp.h:129`; `LedgerMaster.cpp:637-650, 2120-2175` |
| S10: 0 rotations across 310 stale/syncing ledgers; 2 after recovery | `scripts/load_harness.py` | `outputs/S10-rotation-deferred-while-stale.json` (steps, events) | `SHAMapStoreImp.cpp:675-695` |
| Control effectiveness (17 MEASURED, 2 UNMEASURED) | `scripts/measure_controls.py` | `outputs/controls.json`, `outputs/controls.csv` | `docs/source-inventory.md` (per-control sources) |
| Severity-ranked matrix (1 HIGH, 4 MEDIUM, 5 LOW, 1 INFO) | `scripts/build_matrix.py` | `outputs/matrix.json`, `outputs/matrix.csv` | `scenarios/*.json` (`severity`, `severity_reason`) |
| Reproduction (fresh copy, exit 0, outputs identical) | `scripts/make_reproduction_transcript.py` | `outputs/fresh-clone-reproduction.log` | `scripts/run_all.sh`, `scripts/verify_digests.sh` |
