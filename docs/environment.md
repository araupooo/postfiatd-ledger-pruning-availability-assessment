# Test environment

## What was tested

A faithful protocol-level simulator of postfiatd ledger pruning,
history retention, ledger fetch, and state sync, in
`scripts/simulator.py`, driven by `scripts/load_harness.py` over the
11 scenario definitions in `scenarios/`. The simulator re-implements
the decision logic of the pinned code (see `docs/source-inventory.md`
for every cited file and line) over a modeled ledger chain. It does
not build or run postfiatd: a full build was attempted for real in an
earlier pack in this series and proved too heavy for this environment
(Conan dependency fetch stalled at grpc/1.50.1 and a VM restart killed
the retry). All measured results in this pack are therefore
**SIMULATED** — the parameters, gates, thresholds, and order of
operations are the pinned code's; the ledger contents, peer latencies,
and node failures are deterministic stand-ins.

## The model

- **Ledger chain.** Ledgers are numbered sequentially from 1. One
  close = 4000 ms of virtual time (a modeling choice; the pinned code
  does not fix a close interval). A ledger's "hash" is the SHA-256 of
  the string formed by "postfiatd-ledger-" followed by the decimal
  sequence number (for example, "postfiatd-ledger-1257") — a stand-in
  for a real ledger hash, deterministic and collision-free for the
  ranges used.
- **Node state.** A modeled node holds: a SQL Ledgers table
  (`seq -> hash`), a node store (seqs whose objects exist), a
  LedgerHistory in-memory cache (seq -> hash), a complete-ledgers set,
  and the pruning state (`lastRotated`, `canDelete`,
  `minimumOnline_`, mode, validated age). The cache starts with only
  the validated ledger (the tip), as on a restarted node; everything
  else is reached through the SQL fallback (`loadByIndex` /
  `loadByHash`), exactly as the pinned code does on a cache miss.
- **Peers.** A modeled peer holds a contiguous range
  `[min_seq, tip]` and answers with a deterministic latency of 40-900
  ms derived from the SHA-256 of the string formed by "peer-",
  the decimal peer id, "-ledger-", and the decimal sequence number
  (for example, "peer-2-ledger-1257"). A peer that does
  not hold a ledger never answers it, so the acquire times out.
- **Acquire.** First attempt contacts 5 peers; each timeout adds 3
  more (`peerCountStart = 5`, `peerCountAdd = 3`,
  `InboundLedger.cpp:43-74`). Each timeout costs 3000 ms
  (`ledgerAcquireTimeout`). The acquire gives up when `timeouts_`
  exceeds 6 — i.e. on the **7th** timeout, after 21,000 ms
  (`InboundLedger.cpp:376-390`, `TimeoutCounter.cpp:95-112`, which
  increments `timeouts_` before calling `onTimer`). A failed hash is
  recorded in the recent-failures set, so a repeat acquire of the same
  hash short-circuits with 0 timeouts (`kReacquireInterval` 5 min,
  `InboundLedgers.cpp:50-51`).
- **Skip list.** `hashOfSeq` resolves an index directly iff it is
  within 256 below the validated sequence or is 0 mod 256
  (`View.h:495-524`: "each ledger contains the hashes of the 256
  previous ledgers"; every 0-mod-256 ledger is enshrined in a
  LedgerHashes page). Otherwise the candidate ledger
  `(requested + 255) & (~255)` is resolved first, then the requested
  hash through the candidate's skip list.

## Fidelity: what the simulator copies exactly

| Pinned behaviour | Simulator |
|---|---|
| `LEDGER_HISTORY` 256, `FETCH_DEPTH` 1,000,000,000 defaults (`Config.h:224-225`) | Config values in each scenario file |
| `[ledger_history]` / `[fetch_depth]` parsing (`Config.cpp:652-673`) | Scenario config values (`full`/`none`/number) |
| Rotation gate: `validatedSeq >= lastRotated + deleteInterval_ && canDelete_ >= lastRotated - 1 && healthWait() == keepGoing` (`SHAMapStoreImp.cpp:331-332`) | `Node._on_ledger_closed` |
| `clearPrior`: `minimumOnline_ = lastRotated + 1`, `clearPriorLedgers`, three `clearSql` calls (`SHAMapStoreImp.cpp:619-676`) | `Node._clear_prior` (Ledgers table modeled row-for-row; the Transactions and AccountTransactions tables follow the same batched routine in the pinned code but their row counts are not modeled) |
| `clearSql` batches of `deleteBatch_ = 100` with `backOff_ = 100ms` between batches (`SHAMapStoreImp.cpp:550-600`) | `Node._clear_sql` |
| `clampFetchDepth` = `min(fetch_depth, deleteInterval_)` when online delete is on (`SHAMapStoreImp.h:129`) | `Node._clamp_fetch_depth` |
| `minimumOnline`: stored floor when online delete is on, else `minSqlSeq()` (`SHAMapStoreImp.cpp:711-720`) | `Node.minimum_online` |
| `healthWait`: wait while mode != FULL or validated age > 60s (`SHAMapStoreImp.cpp:675-695`) | `Node._health_ok` |
| `shouldAcquire` (`LedgerMaster.cpp:75-99`) | `Node.should_acquire` |
| `getEarliestFetch` (`LedgerMaster.cpp:637-650`) | `Node.get_earliest_fetch` |
| `walkHashBySeq` + `getCandidateLedger` (`LedgerMaster.cpp:1663-1730`, `View.h:517-524`) | `Node._walk_hash_by_seq` |
| `getLedgerHashForHistory` (`LedgerMaster.cpp:1208-1228`) | `Node._hash_for_history` |
| `fetchForHistory` (`LedgerMaster.cpp:1825-1915`) | `Node.fetch_for_history`, including the fetch-pack prefetch of `ledger_fetch_size_` ledgers on a failed acquire |
| `tryFill` (`LedgerMaster.cpp:651-720`) | `Node._try_fill` |
| `doAdvance` history branch (`LedgerMaster.cpp:1940-2000`) | `Node.backfill` (one pass: highest missing ledger first, `shouldAcquire` gate, `fetchForHistory`) |
| `setFullLedger` / `clearLedger` / `clearPriorLedgers` (`LedgerMaster.cpp:826-860, 514-517, 1799-1804`) | `Node._set_full_ledger` / `_clear_ledger` / `_clear_prior_ledgers` |
| `getValidatedRange` / `getCompleteLedgers` (`LedgerMaster.cpp:569-620, 1615-1620`) | `Node.validated_range` / `complete_ledgers_str` |
| `LedgerHistory` insert / get / `fixIndex` / `clearLedgerCachePrior` (`LedgerHistory.cpp:55-157, 536-558`) | `Node` cache methods (`fixIndex` itself is not modeled; see L5) |
| `InboundLedgers::acquire` refusal (`InboundLedgers.cpp:70-130`) | `Node.acquire` (needs-network-ledger refusal; the state is never set in any scenario, so the refusal never fires — control C17 is UNMEASURED) |
| `getLedgerByContext` (`RPCHelpers.cpp:1030-1145`) | `Node.rpc_ledger` (exactly-one rule, age gate at 2 min, index bounds, candidate-ledger acquire, `lgrNotFound` / `rpcNOT_READY` paths) |
| `doCanDelete` (`CanDelete.cpp`) | `Node.rpc_can_delete` (`never`/`always`/`now`/hash/integer) |
| `makeFetchPack` earliest gate (`LedgerMaster.cpp:2120-2175`) | `Node.peer_fetch_pack` |
| `doLedger` (`LedgerCleaner.cpp:272-330`) | `Node.cleaner_do_ledger` |

## Limitations (what the simulator does NOT model)

- **L1 — No real postfiatd binary.** Every result is SIMULATED. The
  simulator copies the pinned decision logic, but it cannot measure
  real disk I/O, real network behaviour, real SHAMap hashing, or real
  consensus interaction.
- **L2 — Synchronous acquires.** In the pinned code an acquire is
  asynchronous: the RPC can return an in-progress `InboundLedger`
  JSON ("acquiring ledger...") while the fetch continues. The
  simulator's acquires complete or fail synchronously, so the
  in-progress outcome is never produced (counter `rpc_acquiring`
  stays 0). The "acquiring ledger containing requested index" error
  text is still exercised when the candidate-ledger acquire fails.
- **L3 — One `doAdvance` pass per backfill step.** The real node
  re-runs `doAdvance` repeatedly; a failed missing ledger is retried
  on later passes after the 5-minute reacquire interval
  (`InboundLedgers.cpp:50-51`). The simulator models one pass and
  halts on the first failure, so the repeated cost of retrying a
  failed ledger (7 timeouts per pass) is measured once, not per pass.
- **L4 — Write load and fee load are not modeled.** The `doAdvance`
  history branch also requires write load < 8192 and the node not to
  be fee-loaded (`LedgerMaster.cpp:1953-1954`). The scenarios assume
  an unloaded node; a loaded node would backfill less.
- **L5 — `fixIndex` is not modeled.** `doLedger` calls
  `fixIndex` to repair a wrong history-index entry
  (`LedgerCleaner.cpp:300-304`). The simulator's cleaner models the
  acquire, the SQL-mismatch re-save, and the missing-nodes branches,
  but not the index repair.
- **L6 — Acquired ledgers are stored on acquire.** In the simulator,
  a successful `acquire()` stores the ledger (`setFullLedger`). In
  the pinned code the caller stores it (e.g. `fetchForHistory`
  calls `setFullLedger` after a successful acquire). The measured
  outcomes (served / not-served counts, ranges, counters) do not
  depend on this difference.
- **L7 — The `set_fetch_depth` step stands in for a second node.**
  S9 part 2 changes `fetch_depth` mid-run; a real operator would
  start a second node with `[fetch_depth] 100`. The clamp arithmetic
  is the same function either way (`SHAMapStoreImp.h:129`), and the
  scenario file says so.
- **L8 — Parent hash is not modeled.** `doLedger`'s SQL-mismatch
  check compares hash *and* parent hash
  (`LedgerCleaner.cpp:292-294`); the simulator compares the hash
  only. Ledger hashes are deterministic stand-ins, not real hashes.
- **L9 — Node size is fixed at `ledger_fetch_size = 2`.** The
  pinned code sizes it by node size (`{2,3,4,5,8}`,
  `Config.cpp:125`); all scenarios use the `tiny` value 2.
- **L10 — The Transactions and AccountTransactions tables are not
  modeled row-for-row.** `clearPrior` clears them with the same
  batched routine as the Ledgers table; only the Ledgers table's row
  and batch counts are measured.
