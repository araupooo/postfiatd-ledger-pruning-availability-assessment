# Source inventory

Pinned postfiatd commit: `0085a1ff885d6a446369cf73a4430f75af22be55`
(2026-10-10). Every file below was verified blob-by-blob: the local
`git hash-object` SHA and byte size agree with the GitHub API tree for
that commit (22/22 agree, tree not truncated). Line numbers were read
with `grep -n` / `sed -n` on the local checkout at that commit, never
from a raw-file fetch.

| # | File | Blob SHA (first 12) | Size | Cited lines | What is cited |
|---|------|---------------------|------|-------------|---------------|
| 1 | `src/xrpld/core/Config.h` | `06cd0d24d863` | 13386 | 224-225, 49-51 | `LEDGER_HISTORY = 256`, `FETCH_DEPTH = 1000000000` defaults; `SizedItem::ledgerFetch` enum |
| 2 | `src/xrpld/core/detail/Config.cpp` | `19b33b251ab2` | 43477 | 125, 415-416, 652-673 | `ledgerFetch` values `{2,3,4,5,8}` by node size; standalone forces `LEDGER_HISTORY = 0`; `[ledger_history]` / `[fetch_depth]` parsing (`full` → max, `none` → 0, minimum fetch depth 10) |
| 3 | `src/xrpld/core/ConfigSections.h` | `db9937b7fa1c` | 4258 | 53, 58 | Section names `fetch_depth`, `ledger_history` |
| 4 | `src/xrpld/app/misc/SHAMapStore.h` | `d2836be2874e` | 3618 | 43, 55, 62, 66, 72, 76, 99 | Interface: `onLedgerClosed`, `clampFetchDepth`, `setCanDelete`, `advisoryDelete`, `getLastRotated`, `getCanDelete`, `minimumOnline` |
| 5 | `src/xrpld/app/misc/SHAMapStoreImp.h` | `d9abe4f5ed2c` | 7430 | 101-109, 125-132, 137-141 | `advisoryDelete_ = false`, `deleteBatch_ = 100`, `backOff_ = 100ms`, `ageThreshold_ = 60s`, `recoveryWaitTime_ = 5s`; `clampFetchDepth` (`min(fetch_depth, deleteInterval_)`); `setCanDelete` (only when `advisoryDelete_`) |
| 6 | `src/xrpld/app/misc/SHAMapStoreImp.cpp` | `080e0d016fd8` | 23426 | 87-157, 224, 289-350, 331-332, 550-600, 619-676, 675-695, 711-720 | Constructor reads `[node_db] online_delete` (121), `delete_batch` (126), `back_off` (132), `age_threshold` (135), `recovery_wait_time` (137), `advisory_delete` (139); `onLedgerClosed` (224); `run()` rotation gate (331-332: `validatedSeq >= lastRotated + deleteInterval_ && canDelete_ >= lastRotated - 1 && healthWait() == keepGoing`); `clearSql` batched delete (550-600, batch step 584, back-off sleep 595); `clearPrior` (619-676: `minimumOnline_ = lastRotated + 1` at 623, `clearPriorLedgers`, three `clearSql` calls); `healthWait` (675-695: waits while mode != FULL or age > 60s); `minimumOnline` (711-720: stored floor when online delete is on, else `minSqlSeq()`) |
| 7 | `src/xrpld/app/ledger/detail/LedgerMaster.cpp` | `67826c253286` | 70382 | 67, 70, 72-99, 110-113, 514-517, 569-620, 637-650, 651-720, 826-860, 1208-1228, 1615-1620, 1663-1730, 1730-1760, 1766-1780, 1799-1804, 1807, 1825-1915, 1940-2000, 2120-2175, 2259-2262 | `MAX_LEDGER_AGE_ACQUIRE` 1 min (67), `MAX_WRITE_LOAD_ACQUIRE` 8192 (70); `shouldAcquire` helper (72-99); constructor `fetch_depth_` from `clampFetchDepth`, `ledger_history_`, `ledger_fetch_size_` (110-113); `clearLedger` (514-517); `getFullValidatedRange` / `getValidatedRange` (569-620); `getEarliestFetch` (637-650); `tryFill` (651-720); `setFullLedger` (826-860); `getLedgerHashForHistory` (1208-1228); `getCompleteLedgers` (1615-1620); `walkHashBySeq` (1663-1730); `getLedgerBySeq` (1730-1760); `getLedgerByHash` (1766-1780); `clearPriorLedgers` (1799-1804); `clearLedgerCachePrior` (1807); `fetchForHistory` (1825-1915, fetch-pack prefetch near 1908); `doAdvance` history branch (1940-2000: sync/age/load gates 1953-1954, `shouldAcquire` call, `fetchForHistory` call); `makeFetchPack` (2120-2175, earliest gate at 2162: `have->info().seq < getEarliestFetch()` → `feeMalformedRequest` "get_object ledger early"); `minSqlSeq` (2259-2262) |
| 8 | `src/xrpld/app/ledger/LedgerHistory.h` | `33f8bf1d9612` | 5192 | 47, 60, 64, 101, 104 | `insert`, `getLedgerBySeq`, `getLedgerByHash`, `fixIndex`, `clearLedgerCachePrior` declarations |
| 9 | `src/xrpld/app/ledger/LedgerHistory.cpp` | `ccec209bd49e` | 18377 | 55-75, 86-122, 123-157, 536-548, 550-558 | `insert` (validated only, 55-75); `getLedgerBySeq` falls back to `loadByIndex` from SQL (86-122); `getLedgerByHash` falls back to `loadByHash` (123-157); `fixIndex` (536-548); `clearLedgerCachePrior` (550-558) |
| 10 | `src/xrpld/app/ledger/detail/InboundLedgers.cpp` | `b05268f65b8b` | 13824 | 50-51, 70-130, 247 | `kReacquireInterval` 5 min (50-51); `acquire` (70-130: refuses when the node needs a network ledger and reason is not GENERIC/CONSENSUS, 82-85); `isFailure` (247) |
| 11 | `src/xrpld/app/ledger/InboundLedger.h` | `e8f244bfc031` | 4991 | 45-49 | `Reason` enum: HISTORY, GENERIC, CONSENSUS |
| 12 | `src/xrpld/app/ledger/detail/InboundLedger.cpp` | `47d546c3af38` | 38190 | 43-74, 376-390 | Timeout constants: `peerCountStart = 5`, `peerCountAdd = 3`, `ledgerTimeoutRetriesMax = 6`, `ledgerBecomeAggressiveThreshold = 4`, `missingNodesFind = 256`, `reqNodesReply = 128`, `reqNodes = 12`, `ledgerAcquireTimeout = 3000ms` (43-74); give-up when `timeouts_ > 6` (376-390) |
| 13 | `src/xrpld/app/ledger/detail/TimeoutCounter.cpp` | `e81ec6574d22` | 3552 | 95-112 | `invokeOnTimer`: on a timer expiry with no progress, `++timeouts_`, then `onTimer` |
| 14 | `src/xrpld/app/ledger/detail/TimeoutCounter.h` | `85ce6fc3b43a` | 5212 | 132 | `timeouts_` member |
| 15 | `src/xrpld/app/ledger/detail/LedgerCleaner.cpp` | `7c0dccfb9b44` | 15190 | 272-330 | `doLedger`: acquire by hash (GENERIC); unavailable → `clearLedger` + retry acquire, return false (278-288); SQL mismatch → re-save transactions (292-298); `fixIndex` (300-304); missing nodes on `walkLedger` → `clearLedger` + retry, return false (306-313); save when `doTxns` (315-319) |
| 16 | `src/xrpld/rpc/detail/RPCHelpers.cpp` | `edb91611bec2` | 35977 | 352, 1030-1145 | Staleness check against `maxValidatedLedgerAge` (352); `getLedgerByContext` (1030-1145: exactly one of `ledger_hash`/`ledger_index` at 1042, validated-age check at 1061, "Ledger index too large" at 1072, "Ledger index too small" at 1074, candidate-ledger acquire at 1101, `find()` in-progress path at 1140, `rpcNOT_READY` at 1144) |
| 17 | `src/xrpld/rpc/detail/Tuning.h` | `4f4a8be1bf76` | 3330 | 65 | `maxValidatedLedgerAge = 2 minutes` |
| 18 | `src/xrpld/rpc/handlers/CanDelete.cpp` | `b7056e74391a` | 3420 | 37, 61-85 | Requires `advisoryDelete()` else `rpcNOT_ENABLED` (37); `never` → 0 (61-63), `always` → max (65-67), `now` → `getLastRotated()` (`rpcNOT_READY` if 0, 69-73), hash → sequence via `getLedgerByHash` else `lgrNotFound` "ledgerNotFound" (75-81), otherwise `rpcINVALID_PARAMS` (83-85) |
| 19 | `src/xrpld/rpc/handlers/LedgerRequest.cpp` | `fed89daaf202` | 1784 | 36-38 | `doLedgerRequest` resolves through `getLedgerByContext` |
| 20 | `src/xrpld/nodestore/Database.h` | `403a5ea5eec3` | 9574 | 220-241 | `earliestLedgerSeq()` (221-225); default `XRP_LEDGER_EARLIEST_SEQ` (32570), configurable via `earliest_seq` under `[node_db]` (235-241) |
| 21 | `src/xrpld/app/rdb/detail/State.cpp` | `c3de860689cb` | 4042 | 41-90 | `CanDelete` table (`CREATE TABLE` 41-43, `getCanDelete` 81-84, `setCanDelete` 91-94); `lastRotated` persisted alongside |
| 22 | `include/xrpl/ledger/View.h` | `8e0a9dd5ff8c` | 38011 | 495-524 | `hashOfSeq` doc: a ledger contains the hashes of the 256 previous ledgers, so a sequence outside that range returns nullopt; `getCandidateLedger` (517-524): `(requested + 255) & (~255)`, 0 mod 256, retrievable via the skip list |

## Corrections to earlier research notes

Two paths in the pre-build research notes were wrong and are corrected
here (the line numbers were right; the directories were not):

- `SHAMapStoreImp.cpp` / `SHAMapStoreImp.h` live in
  `src/xrpld/app/misc/`, not `src/xrpld/app/ledger/detail/`.
- `LedgerHistory.cpp` lives in `src/xrpld/app/ledger/`, not
  `src/xrpld/app/ledger/detail/`.
- `maxValidatedLedgerAge` lives in `src/xrpld/rpc/detail/Tuning.h:65`,
  not in a ledger `Tuning.h`.
