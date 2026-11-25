# Operator remediation report

Severity-ranked, most urgent first. Each item names the finding it
answers, the concrete operator action, and the evidence that the
action addresses the measured behaviour. All numbers are SIMULATED.

## R1 — HIGH — Keep at least one full-history peer reachable (answers F4)

- **Finding.** With no full-history peer, every pruned-range request
  fails: S2 measured 7/7 `lgrNotFound`, 4 first attempts burning 7
  timeouts (21 s) each, 84,000 ms wasted in total. The data is
  unrecoverable from the available peer set.
- **Action.** Maintain peering with at least one node that holds full
  history (a history node or an archive node), and monitor that it is
  actually serving: request a ledger below your prune floor
  periodically (e.g. `ledger` with a low `ledger_index`) and alert
  when it returns `lgrNotFound`. Do not assume a peer holds history
  because it is connected — a peer can be connected and pruned.
- **Why it matters.** S1 shows the same node serves 8/8 requests
  when a full peer exists. The difference between "pruning is
  invisible" and "history is gone" is exactly one peer.

## R2 — HIGH — Do not rely on backfill to recover history below the window (answers F3, F5, F6)

- **Finding.** The background backfill cannot extend history below
  the SQL minimum without an online-delete floor (S3: 0 acquired,
  halt at 1743), and with a floor it stops at the floor (S5: 743
  acquired, halt at 1256). Below the floor nothing is ever attempted.
- **Action.** Treat the prune floor as permanent. Before enabling
  online delete or lowering `[ledger_history]`, export or archive the
  ledgers you may need (an offline copy of the ledger database, or a
  second node with `online_delete` off and `[ledger_history] full`).
  If history below the window is already gone and no peer holds it,
  there is no recovery path in the pinned code — do not wait for the
  backfill to fix it.
- **Why it matters.** Operators who discover a gap below the window
  usually assume the node will "catch up" once peers are available.
  It will not: the gate refuses before any acquire is attempted.

## R3 — MEDIUM — The cleaner cannot repair what no peer holds (answers F9)

- **Finding.** S7: the cleaner repaired 3/4 ledgers and dropped the
  fourth (1000) from the complete set because no peer held it. The
  validated range became [1001, 2000].
- **Action.** Before running `ledger_cleaner` (or relying on it after
  a disk incident), confirm a peer holds the affected range. After a
  cleaner run, check `getValidatedRange` / the server `complete_ledgers`
  for new gaps: a dropped ledger is silent — the cleaner logs it and
  moves on.
- **Why it matters.** A cleaner run on a pruned network can widen a
  gap instead of closing it, and the gap only shows up when someone
  asks for that ledger.

## R4 — MEDIUM — Expect 21 s per failed historical fetch, and budget for it (answers F4, F5)

- **Finding.** A failed acquire burns 7 timeouts of 3000 ms
  (21,000 ms), not 6: the code fails when `timeouts_` exceeds 6
  (`InboundLedger.cpp:376-390`, `TimeoutCounter.cpp:95-112`). S2
  measured 84,000 ms wasted across 7 failed requests; S4 measured
  21,000 ms for the single failed floor ledger.
- **Action.** Do not issue historical fetches in a tight loop against
  a pruned peer set: each distinct missing ledger costs up to 21 s
  of acquire time, and the RPC caller waits. Batch historical
  requests, cache the results, and treat a first `lgrNotFound` for a
  range as a signal to stop asking for that range (the
  recent-failures cache short-circuits repeats of the *same* hash for
  5 minutes, but a *different* missing ledger costs another 21 s).
- **Why it matters.** A client that pages through a pruned range
  ledger-by-ledger pays ~21 s per ledger. The failure cache helps
  only for repeats of the same ledger.

## R5 — MEDIUM — Set the fetch-depth clamp deliberately (answers F11)

- **Finding.** `clampFetchDepth` is `min(fetch_depth,
  online_delete)` when online delete is on, so at the default
  `fetch_depth` the online-delete interval binds (S9: clamp 256,
  earliest fetch 1744). Narrowing `fetch_depth` to 100 raises the
  earliest fetch to 1900 and refuses two more fetch-pack roots.
- **Action.** If you serve fetch packs to peers, set `[fetch_depth]`
  explicitly and check `getEarliestFetch` behaviour against your
  online-delete interval: the tighter of the two decides what you
  will serve. If you lower `fetch_depth` to save disk, expect peers
  to receive `feeMalformedRequest` "get_object ledger early" for
  roots below the new earliest fetch.

## R6 — LOW — Use `can_delete` "now" for one rotation, "always" for a policy (answers F8)

- **Finding.** `can_delete now` sets `can_delete` to `lastRotated`,
  which satisfies `canDelete_ >= lastRotated - 1` exactly once: S6
  measured 1 rotation after `now` (at tip 1601), then no more until
  `always`. `never` blocks all rotation; a hash authorises up to that
  ledger.
- **Action.** Use `now` when you want to authorise a single rotation
  (e.g. after freeing disk by hand). Use `always` when you want
  pruning to proceed unattended. Do not use `now` repeatedly and
  expect continuous pruning — each call authorises one rotation.
  Remember a delayed rotation sets `lastRotated` to the current tip,
  so the next interval is counted from the late tip, not from the
  gate threshold.

## R7 — LOW — Do not treat hash lookups as staleness-proof (answers F10)

- **Finding.** At validated age 121 s, `ledger_index` requests
  return `rpcNOT_SYNCED` (`rpcNO_CURRENT` on v1) while `ledger_hash`
  requests are served. The age check exists only in the index branch.
- **Action.** If you monitor node staleness through RPC, use
  `ledger_index` requests (or `server_info` / `getValidatedLedgerAge`
  directly), not hash lookups. A hash lookup succeeding says nothing
  about how stale the node is.

## R8 — LOW — Expect rotation to pause while the node is unhealthy, and let it catch up (answers F12)

- **Finding.** Rotation is deferred while the validated age exceeds
  60 s or the node is not FULL (S10: 0 rotations across 310
  ledgers), then fires on the first healthy close (tip 1311) and
  again one interval later (1567). No data is lost beyond the
  configured interval.
- **Action.** Do not force rotation during an outage or a sync: the
  deferral is the safety mechanism. After recovery, expect a burst of
  deletions (S10: 1,310 rows in 14 batches across 2 rotations) and
  size the delete batch/back-off accordingly if disk I/O is a
  concern.
