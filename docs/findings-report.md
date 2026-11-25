# Findings report

All numbers are SIMULATED (see `docs/environment.md`). Each finding
names the scenario, the measured numbers, and the output files that
carry them.

## F1 — Pruning deletes exactly as configured (S1, S6, S10)

- S1 (`outputs/S1-aggressive-pruning.json`): 2 rotations (tips 1256,
  1512) over 600 validated ledgers; 1,255 SQL rows deleted in 13
  batches (10 + 3); no batch exceeded 100 rows. Final SQL range
  1005-1600 (the RPC step re-acquired 4 ledgers below the floor —
  see F2); `minimumOnline` 1257; `getEarliestFetch` 1344.
- S6 (`outputs/S6-can-delete-advisory.json`): 4 rotations (tips 1301,
  1601, 1901, 2157); 1,900 rows deleted in 20 batches.
- S10 (`outputs/S10-rotation-deferred-while-stale.json`): 2 rotations
  (tips 1311, 1567) after the deferral; 1,310 rows deleted in 14
  batches.
- The rotation gate, the batch size, and the back-off are all
  measured exactly as the pinned code states them (controls C00, C14,
  C15: 100% effectiveness).

## F2 — A full peer makes pruning invisible to RPC, but the refill is piecemeal (S1)

- S1: all 8 RPC fetches served (8/8), including 1005, 1100, and 1200,
  which were pruned from SQL. Each cost one peer acquire (1,377 ms
  total); the 1005 request cost one extra acquire for its candidate
  ledger 1024 (4 acquires total).
- The re-acquired ledgers (1005, 1024, 1100, 1200) sit below
  `minimumOnline` (1257) as isolated entries: the SQL minimum drops
  to 1005 while `minimumOnline` stays 1257, and the validated range
  stays [1256, 1600]. On-demand RPC refills do not extend the
  validated range — only the background backfill does, and it refuses
  below the window (F3).
- Consequence: a pruned node with a full peer can answer any single
  historical query, but it cannot rebuild a contiguous history below
  its prune floor through RPC alone.

## F3 — Backfill cannot extend below the SQL minimum without an online-delete floor (S3)

- S3 (`outputs/S3-partial-history-node.json`): the backfill acquired
  **0** ledgers and halted at 1743 (`gate-refused`). The node held
  1744-2000 in SQL and a full-history peer held everything, but
  `shouldAcquire(1743)` is false: 2000-1743 = 257 > 256, and 1743 is
  below `minimumOnline`, which without online delete is the SQL
  minimum (1744 at halt time).
- The third disjunct of `shouldAcquire` ("candidate >=
  minimumOnline") only helps when the node already holds ledgers
  below the window. It can never extend the SQL minimum downward on
  its own: the floor moves only when the node acquires a lower
  ledger, and acquiring a lower ledger requires passing the gate.
  The only way down is the online-delete floor (`minimumOnline_`),
  which is what S4/S5 exercise (F5, F6).
- An operator who configures `[ledger_history] 256` with no online
  delete and then loses history below the window cannot get it back
  through the background backfill, however good the peers are.

## F4 — Pruned-range fetch with no full peer fails hard (S2, HIGH)

- S2 (`outputs/S2-pruned-range-fetch-no-full-peer.json`): 7 of 7
  pruned-range requests return `lgrNotFound`; 3 of 3 in-window
  requests served.
- The 4 first attempts each burn 7 acquire timeouts (21,000 ms).
  The 3 repeats of the failed candidate hash (1024) short-circuit on
  the recent-failures cache with 0 timeouts and 0 ms. Total wasted
  acquire time: 84,000 ms across 7 requests.
- Failure modes split two ways: 4 requests fail at the candidate
  step (the 256-boundary reference ledger 1024 is not held and no
  peer holds it — the RPC returns "acquiring ledger containing
  requested index"); 2 fail on the target acquire after the hash was
  resolved through the held candidate 1280; 1 fails on a direct hash
  acquire.
- The data is unrecoverable from the available peer set. The only
  remedy is a peer that holds the range.

## F5 — Backfill from a pruned peer stops one ledger short of the floor (S4, MEDIUM)

- S4 (`outputs/S4-backfill-from-pruned-peer.json`): the backfill
  acquired 742 ledgers (1258-1999) from the pruned peer, then the
  floor ledger 1257 failed after 7 timeouts (21,000 ms) because no
  peer holds it. Halt: `fetch-failed` at 1257. Final validated range
  [1258, 2000]; SQL range 1258-2000 (743 rows).
- The fetch-pack prefetch fired once after the failure and requested
  0 ledgers: neither target hash (1257, 1256) was resolvable from the
  skip list, so there was nothing to prefetch.
- Everything below the floor (1-1256) is never attempted by design.
  The real node would retry 1257 on later `doAdvance` passes after
  the 5-minute reacquire interval, burning 7 timeouts per pass
  (see `docs/environment.md`, L3).

## F6 — With a full peer, the floor binds, not the peer (S5, LOW)

- S5 (`outputs/S5-backfill-with-full-peer.json`): the backfill
  acquired 743 ledgers (1257-1999) and halted at 1256
  (`gate-refused`): 2000-1256 = 744 > 256 and 1256 < `minimumOnline`
  (1257). Final validated range [1257, 2000]; SQL range 1257-2000
  (744 rows). 743 acquires, 0 failures, 240,506 ms total.
- The contrast with S4 isolates the cause: the peer can supply
  everything, but the gate refuses below the floor. The floor — not
  peer availability — is the binding constraint.

## F7 — RPC fetches what backfill refuses (S3)

- S3: after the backfill halted at 1743 with 0 acquired, on-demand
  RPC fetched 15 of 15 deep ledgers (1500-1509, 1000-1004) from the
  full peer: 17 acquires, 0 failures, 7,808 ms total.
- The first deep request per 256-block pays 2 acquires (candidate
  ledger + target: 1536 for the 1500s, 1024 for the 1000s);
  subsequent requests in the same block pay 1.
- Stored history still never grows past the window except for the
  exact ledgers requested: final complete set is
  `1000-1004,1024,1500-1509,1536,1744-2000`, and the validated range
  stays [1744, 2000]. Every deep lookup remains a live peer fetch.

## F8 — Advisory `can_delete` works exactly as documented (S6, LOW)

- S6: `never` held rotations at 0 for 300 ledgers; the hash of
  ledger 1200 authorised up to 1200 (1 rotation, at tip 1301);
  `now` set `can_delete` to `lastRotated` (1301), which satisfies
  `canDelete_ >= lastRotated - 1`, so it authorised exactly 1 more
  rotation (at tip 1601); `always` released the rest (2 rotations,
  at 1901 and 2157). Total: 4 rotations, 1,900 rows, 20 batches.
- A rotation sets `lastRotated` to the current validated tip, not to
  the gate threshold — so a rotation delayed by `can_delete` fires
  late and shifts the next interval (first rotation at 1301, not
  1256).

## F9 — LedgerCleaner repair depends on peer availability (S7, MEDIUM)

- S7 (`outputs/S7-ledger-cleaner-repair.json`): 3 of 4 ledgers
  cleaned. Ledger 1500 (nodes missing) was recovered from the peer;
  ledger 1600 (corrupted SQL hash) was re-saved after the mismatch
  was detected; ledger 1700 was already clean. Ledger 1000 failed:
  no peer holds it, so the cleaner cleared it from the complete set
  and the validated range became [1001, 2000].
- Cost: 5 acquire attempts, 7 timeouts (the first attempt for 1000;
  the retry short-circuited on the recent-failures cache), 22,168 ms
  total.
- A pruned ledger with no full peer cannot be repaired. The cleaner
  can only restore what some peer still holds.

## F10 — The RPC age gate covers index requests only (S8, LOW)

- S8 (`outputs/S8-rpc-resolution-matrix.json`): at validated age
  121 s (above the 2-minute `maxValidatedLedgerAge`):
  - `ledger_index` 1999 → `rpcNOT_SYNCED`
  - `ledger_hash` 1999 → served
  - `ledger_index` 1999, API v1 → `rpcNO_CURRENT`
- Both fields set → parameter error ("Exactly one of ledger_hash and
  ledger_index can be set."). Index 2000 (at the tip) → "Ledger index
  too large". Index 0 → "Ledger index too small". At age 0 s, index
  and hash 1999 are both served.
- An operator relying on `rpcNOT_SYNCED` to detect a stale node will
  see hash lookups succeed on that same stale node. The age check
  exists only in the `ledger_index` branch
  (`RPCHelpers.cpp:1030-1145`).

## F11 — The fetch-depth clamp binds before fetch_depth does (S9, MEDIUM)

- S9 (`outputs/S9-fetch-depth-clamp.json`): with the default
  `fetch_depth` (1,000,000,000) clamped to `online_delete` (256),
  `getEarliestFetch` is 1744. Fetch-pack roots 1000 and 1500 are
  refused because the node does not hold those ledgers; roots 1744,
  1900, 2000 are served.
- With `fetch_depth` narrowed to 100, the clamp is 100 and
  `getEarliestFetch` rises to 1900: roots 1744 and 1800 are refused
  with "peer requests fetch pack that is too early"
  (`feeMalformedRequest` "get_object ledger early" in the pinned
  code); roots 1900 and 2000 are served.
- Total: 5 served, 4 refused across both parts.

## F12 — Rotation is deferred while stale or syncing, then catches up (S10, LOW)

- S10 (`outputs/S10-rotation-deferred-while-stale.json`): 0 rotations
  across 300 validated ledgers with age pinned at 61 s (above the
  60 s threshold) and 10 more while the node was syncing. On the
  first close after the node returned to FULL with age 0 s, rotation
  fired (tip 1311), and again one interval later (tip 1567).
  1,310 rows deleted in 14 batches; final SQL range 1311-1610.
- No data is lost beyond the configured interval; the deferral only
  delays the deletion.

## F13 — Baseline (S0, INFO)

- S0 (`outputs/S0-baseline-full-history.json`): 120 of 120 RPC fetches
  served locally, 0 acquires, 0 rotations. Final tip 1120, SQL range
  1-1120. The control case against which every other scenario is
  read.
