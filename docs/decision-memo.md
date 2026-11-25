# Decision memo: ledger pruning and historical data availability

Pinned postfiatd commit: `0085a1ff885d6a446369cf73a4430f75af22be55`.
All measured numbers are SIMULATED (protocol-level simulator; see
`docs/environment.md`). All source citations are in
`docs/source-inventory.md`.

## Question

When do postfiatd pruning, partial history, and state sync prevent
operators or auditors from retrieving historical ledgers — and what
should an operator do about it?

## Answer in one paragraph

Pruning deletes exactly as configured and is harmless while a
full-history peer exists (S1: 8/8 RPC fetches served). It becomes
unrecoverable data loss the moment no peer holds the range (S2: 7/7
`lgrNotFound`, 84,000 ms wasted). The background backfill cannot
repair a gap below the 256-ledger window or below the online-delete
floor — it refuses before attempting (S3: 0 acquired; S5: halt at the
floor) — and the ledger cleaner can only restore what some peer holds
(S7: 3/4 cleaned, the fourth dropped). The binding constraints are
the `shouldAcquire` gate, the `minimumOnline` floor, and peer
availability, in that order.

## The chain of reasoning

1. **Pruning is a one-way door with a floor.** Online delete rotates
   when `validatedSeq >= lastRotated + deleteInterval_ &&
   canDelete_ >= lastRotated - 1 && healthWait() == keepGoing`
   (`SHAMapStoreImp.cpp:331-332`). `clearPrior` then sets
   `minimumOnline_ = lastRotated + 1` and deletes SQL rows below
   `lastRotated` in batches of 100 (`SHAMapStoreImp.cpp:619-676,
   550-600`). Measured: S1 deleted 1,255 rows in 13 batches; S6
   deleted 1,900 rows in 20 batches; S10 deleted 1,310 rows in 14
   batches. Nothing deleted is recoverable from the node itself.
2. **The backfill gate, not the peer, usually decides.** `doAdvance`
   fetches history only when in sync, unloaded, and young enough
   (`LedgerMaster.cpp:1940-2000`), and only for ledgers
   `shouldAcquire` allows (`LedgerMaster.cpp:75-99`): at/above the
   tip, within `ledger_history` (256), or at/above `minimumOnline`.
   Measured: S3 halted at 1743 with 0 acquired although a full peer
   held everything; S5 halted at 1256 with 743 acquired although the
   peer held everything below the floor. The gate is the binding
   constraint in both cases.
3. **Without an online-delete floor, the SQL minimum is the floor —
   and it cannot be extended downward.** `minimumOnline()` returns
   the stored floor when online delete is on, else `minSqlSeq()`
   (`SHAMapStoreImp.cpp:711-720`). A node that holds 1744-2000 has
   `minimumOnline` 1744, so `shouldAcquire(1743)` is false, and
   acquiring 1743 is the only way to lower the minimum. Measured in
   S3. This is the least obvious finding in the pack: the third
   disjunct of `shouldAcquire` looks like an escape hatch and is, for
   downward extension, vacuous.
4. **With a floor, the peer decides the last ledger.** S4 (pruned
   peer): 742 acquired, then the floor ledger 1257 failed after 7
   timeouts (21 s) because no peer holds it; the validated range
   stops at [1258, 2000]. S5 (full peer added): 743 acquired, halt at
   the floor by the gate. The floor is reachable only when a peer
   holds the floor ledger.
5. **RPC bypasses the gate, but only one ledger at a time.**
   `getLedgerByContext` (`RPCHelpers.cpp:1030-1145`) acquires directly
   without `shouldAcquire`. Measured: S3 fetched 15/15 deep ledgers
   by RPC after the backfill refused them all, at 17 acquires and
   7,808 ms. But the re-acquired ledgers are isolated entries: the
   validated range stays [1744, 2000]. RPC is a per-ledger escape
   hatch, not a history rebuild.
6. **A failed fetch is expensive and the failure cache only helps
   repeats.** A failed acquire burns 7 timeouts of 3000 ms (21 s):
   the code fails when `timeouts_` exceeds 6
   (`InboundLedger.cpp:376-390`), and the timer increments first
   (`TimeoutCounter.cpp:95-112`). Measured: S2 wasted 84,000 ms on 7
   failed requests — 4 first attempts at 21 s each, 3 repeats of the
   failed candidate hash short-circuited at 0 ms by the
   recent-failures cache (`InboundLedgers.cpp:50-51`, 5-minute
   interval).
7. **The cleaner drops what nobody holds.** `doLedger`
   (`LedgerCleaner.cpp:272-330`) acquires, compares against SQL,
   re-saves on mismatch, and clears the ledger from the complete set
   when the acquire fails. Measured: S7 cleaned 3/4; ledger 1000 was
   dropped and the validated range became [1001, 2000].
8. **Two asymmetries worth knowing.** (a) The RPC age gate covers
   `ledger_index` only: at age 121 s, index → `rpcNOT_SYNCED`,
   hash → served (S8). (b) `can_delete now` authorises exactly one
   rotation, because the gate is `canDelete_ >= lastRotated - 1` and
   `now` sets `can_delete` to `lastRotated` (S6: 1 rotation after
   `now`, then none until `always`).

## What this means for an operator

- **Keep a full-history peer.** It is the single control that turns
  pruning from "invisible" (S1) into "unrecoverable" (S2). Verify it
  serves below your floor; do not trust connectivity alone.
- **Archive before you prune.** The floor is permanent by design.
  There is no code path that recovers history below it once every
  peer has pruned it.
- **Do not page through pruned ranges.** Each distinct missing ledger
  costs up to 21 s of acquire time. A first `lgrNotFound` for a range
  is a signal to stop, not to retry the next ledger.
- **Check the validated range after cleaner runs.** A dropped ledger
  is silent; the gap only shows when someone asks for it.

## What this pack does not establish

- No live node was run. Every number is SIMULATED from the pinned
  parameters (see `docs/environment.md`, L1). A live-node measurement
  could differ in wall-clock costs (disk I/O, real network latency)
  but not in the gate outcomes, which are the pinned code's logic.
- Two controls are UNMEASURED: the fetch-pack prefetch (C16 — invoked
  once, requested 0 ledgers) and the needs-network-ledger acquire
  refusal (C17 — never entered). Neither affects the conclusions
  above; both are stated plainly in `docs/control-inventory.md`.
- The simulator models one `doAdvance` pass per backfill step (L3):
  a real node retries a failed missing ledger on later passes after
  the 5-minute reacquire interval, so the repeated cost of S4's
  failed floor ledger is 7 timeouts per pass, not once.
