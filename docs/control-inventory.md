# Control inventory

Pinned commit: `0085a1ff885d6a446369cf73a4430f75af22be55`.
19 controls inventoried; 17 MEASURED, 2 UNMEASURED. The machine-readable
table is `outputs/controls.json` (and `.csv`); the measurements below
are quoted from it. Effectiveness is measured against the pinned
code's rule, not against an ideal: a control is 100% effective when
it behaved exactly as the code states it in every exercised case.

| ID | Control | Source | Scenarios | Status | Effectiveness |
|----|---------|--------|-----------|--------|---------------|
| C00 | online_delete rotation interval | `SHAMapStoreImp.cpp:331-344` | S1, S6, S10 | MEASURED | 100% — every rotation fired at the first close where the interval, can_delete, and health gates all held; lastRotated jumps to the current tip |
| C01 | can_delete advisory gate | `CanDelete.cpp`; `SHAMapStoreImp.cpp:121-157` | S6 | MEASURED | 100% — 4/4 argument forms behaved as documented (never blocks, hash authorises to that ledger, now authorises exactly one more rotation, always releases all) |
| C02 | shouldAcquire window gate | `LedgerMaster.cpp:75-99` | S3, S4, S5 | MEASURED | 100% — the gate refused exactly where the rule says it must (S3 at 1743, S5 at 1256); S4's halt is a peer failure, not a gate error |
| C03 | minimumOnline floor | `SHAMapStoreImp.cpp:711-720` | S4, S5 | MEASURED | 100% — the floor is honoured as coded in both forms (SQL minimum without online delete, stored floor with it) |
| C04 | clampFetchDepth | `SHAMapStoreImp.h:129` | S9 | MEASURED | 100% — both clamps match min(fetch_depth, online_delete) (256, then 100) |
| C05 | hashOfSeq skip-list resolution + candidate ledger | `LedgerMaster.cpp:1663-1730`; `View.h:506-524` | S2, S3 | MEASURED | 100% — the candidate path behaved as coded in every case (S2: 4 candidate-step failures, 2 target failures via the held candidate 1280, 1 direct hash failure; S3: 15/15 resolved through an acquired candidate) |
| C06 | InboundLedger timeout model (7 x 3000 ms) | `InboundLedger.cpp:43-74, 376-390`; `TimeoutCounter.cpp:95-112` | S2, S7 | MEASURED | 100% — 7 timeouts per failed first attempt; repeats of a failed hash short-circuit via mRecentFailures (S2: 28 timeouts over 7 failed acquires; S7: 7 timeouts for the failed clean) |
| C07 | fetch-pack earliest-fetch gate | `LedgerMaster.cpp:2140-2175` | S9 | MEASURED | 100% — the gate refused exactly the roots below getEarliestFetch (2 too-early refusals) |
| C08 | LedgerCleaner repair | `LedgerCleaner.cpp:273-330` | S7 | MEASURED | 100% as coded when a peer holds the ledger (3/3), 0% when none does (0/1) — the control cannot repair what no peer holds |
| C09 | RPC validated-age gate | `RPCHelpers.cpp:1030-1145`; `Tuning.h:65` | S8 | MEASURED | 50% coverage — fires for ledger_index (1/1), bypassed by ledger_hash (0/1), which has no age check in the pinned code |
| C10 | RPC index bounds and exactly-one rule | `RPCHelpers.cpp:1030-1145` | S8 | MEASURED | 100% — 3/3 parameter errors fired before any fetch was attempted |
| C11 | doAdvance history backfill | `LedgerMaster.cpp:1945-1998` | S3, S4, S5 | MEASURED | 100% — the history branch acquires exactly the ledgers the gate allows (S3 0, S4 742, S5 743), no more |
| C12 | tryFill contiguous marking | `LedgerMaster.cpp:651-720` | S4, S5 | MEASURED | 100% — tryFill marked exactly the contiguous acquired ranges complete (S4 1258-2000, S5 1257-2000) |
| C13 | LedgerHistory SQL fallback | `LedgerHistory.cpp:86-157` | S1, S2 | MEASURED | 100% — every in-window SQL lookup succeeded (5/5: S1 1256/1257, S2 1300/1400/1500) |
| C14 | clearSql batched delete (batch 100) | `SHAMapStoreImp.cpp:560-600` | S1, S6 | MEASURED | 100% — no batch exceeded 100 rows (S1: 1,255 rows in 13 batches; S6: 1,900 rows in 20 batches) |
| C15 | rotation health gate (age <= 60 s, FULL mode) | `SHAMapStoreImp.cpp:680-690` | S10 | MEASURED | 100% — 0 rotations across 300 stale + 10 syncing ledgers; 2 rotations after recovery |
| C16 | fetch-pack prefetch (ledger_fetch_size) | `LedgerMaster.cpp:1825-1915` | — | UNMEASURED | Invoked once (S4, after the failed 1257 acquire) but requested 0 ledgers, because neither target hash (1257, 1256) was resolvable from the skip list. No scenario produced a failed in-window history acquire with resolvable prefetch targets. |
| C17 | needs-network-ledger acquire refusal | `InboundLedgers.cpp:70-125` | — | UNMEASURED | The refusal fires only for a HISTORY/CONSENSUS acquire while the node needs a network ledger; no scenario set that state, so the refusal never ran. |
| C18 | getLedgerBySeq SQL fallback (loadByIndex) | `LedgerMaster.cpp:1730-1760`; `LedgerHistory.cpp:86-122` | S9 | MEASURED | 100% — the fallback found every held ledger and reported every missing one (roots 1000/1500 → no ledger; 1744/1900/2000 resolved) |

## Reading the two UNMEASURED controls

- **C16** is the only control whose code path was entered but not
  exercised: the prefetch ran and correctly requested nothing, which
  confirms the guard (`missing > earliestLedgerSeq` and resolvable
  hashes) but not the prefetch itself. A scenario that fails a
  history acquire for a ledger whose two predecessors are resolvable
  would measure it.
- **C17** is the only control whose code path was never entered. The
  refusal is a one-line guard (`isNeedNetworkLedger() && reason !=
  GENERIC && reason != CONSENSUS`); it needs a node in the
  needs-network-ledger state, which no scenario sets.

## The two partial ratings

- **C09 (50%)** is a coverage gap, not a bug: the age gate is
  written only in the `ledger_index` branch. Hash lookups on a stale
  node succeed by design.
- **C08 (conditional)** is a dependency, not a bug: the cleaner is a
  repair tool, not a recovery tool. It restores what peers hold and
  drops what nobody holds. The operator implication is in
  `docs/remediation-report.md` (R3).
