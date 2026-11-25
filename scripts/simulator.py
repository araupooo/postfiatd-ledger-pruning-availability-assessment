#!/usr/bin/env python3
"""simulator.py — faithful protocol-level simulator of postfiatd ledger
pruning, history retention, ledger fetch, and state sync.

Pinned postfiatd commit: 0085a1ff885d6a446369cf73a4430f75af22be55.
Every control parameter below is taken verbatim from the pinned code;
each is traced to its exact file:line in docs/source-inventory.md.

The simulator does NOT build or run postfiatd. It re-implements the
decision logic of the cited functions over a modeled ledger chain, so
the measured outcomes are SIMULATED (see docs/methodology.md). The
parameters, gates, thresholds, and order of operations are the pinned
code's; the ledger contents, peer latencies, and node failures are
deterministic stand-ins.

Determinism: no wall clock, no random module. All pseudo-randomness
comes from SHA-256 of stable labels. One ledger close = 4000 ms of
virtual time (a modeling choice; the pinned code does not fix a close
interval). Ledger "hashes" are SHA-256 of the string formed by
"postfiatd-ledger-" followed by the decimal sequence number (for
example, "postfiatd-ledger-1257") — stand-ins for real ledger hashes.

Modelled functions (pinned code -> simulator method):
  Config LEDGER_HISTORY / FETCH_DEPTH defaults
      -> Node.__init__ (Config.h:224-225)
  [ledger_history] / [fetch_depth] parsing
      -> config values in the scenario file (Config.cpp:652-673)
  SHAMapStoreImp ctor online_delete / advisory_delete / minimums
      -> Node.__init__ (SHAMapStoreImp.cpp:121-157)
  SHAMapStoreImp::run rotation gate
      -> Node._maybe_rotate (SHAMapStoreImp.cpp:331-344)
  SHAMapStoreImp::clearPrior / clearSql
      -> Node._clear_prior (SHAMapStoreImp.cpp:619-676, 560-600)
  SHAMapStoreImp::clampFetchDepth
      -> Node._clamp_fetch_depth (SHAMapStoreImp.h:129)
  SHAMapStoreImp::minimumOnline
      -> Node.minimum_online (SHAMapStoreImp.cpp:711-720)
  SHAMapStoreImp::healthWait
      -> Node._health_ok (SHAMapStoreImp.cpp:680-690)
  LedgerMaster::shouldAcquire
      -> Node.should_acquire (LedgerMaster.cpp:75-99)
  LedgerMaster::getEarliestFetch
      -> Node.get_earliest_fetch (LedgerMaster.cpp:637-650)
  LedgerMaster::getLedgerBySeq / getLedgerByHash
      -> Node.get_ledger_by_seq / get_ledger_by_hash
         (LedgerMaster.cpp:1730-1780)
  LedgerMaster::walkHashBySeq + getCandidateLedger
      -> Node._walk_hash_by_seq (LedgerMaster.cpp:1663-1730,
         View.h:521-524)
  LedgerMaster::getLedgerHashForHistory
      -> Node._hash_for_history (LedgerMaster.cpp:1208-1228)
  LedgerMaster::fetchForHistory
      -> Node.fetch_for_history (LedgerMaster.cpp:1825-1915)
  LedgerMaster::tryFill
      -> Node._try_fill (LedgerMaster.cpp:651-720)
  LedgerMaster::doAdvance history branch
      -> Node.backfill (LedgerMaster.cpp:1945-1998)
  LedgerMaster::setFullLedger / clearLedger / clearPriorLedgers
      -> Node._set_full_ledger / _clear_ledger / _clear_prior_ledgers
         (LedgerMaster.cpp:826-860, 514-517, 1799-1804)
  LedgerMaster::getValidatedRange / getCompleteLedgers
      -> Node.validated_range / complete_ledgers_str
         (LedgerMaster.cpp:569-620, 1615-1620)
  LedgerHistory insert / getLedgerBySeq / getLedgerByHash / fixIndex /
  clearLedgerCachePrior
      -> Node history-cache methods (LedgerHistory.cpp:55-157, 536-558)
  InboundLedgers::acquire (+ isFailure short-circuit)
      -> Node.acquire (InboundLedgers.cpp:70-125, 247)
  InboundLedger timeouts (5 peers start, +3 per timeout, 3000 ms,
  give up when timeouts_ exceeds 6, i.e. on the 7th timeout)
      -> Node.acquire (InboundLedger.cpp:43-74, 376-390;
         TimeoutCounter.cpp:95-112)
  RPC getLedgerByContext
      -> Node.rpc_ledger (RPCHelpers.cpp:1030-1145)
  RPC doCanDelete
      -> Node.rpc_can_delete (CanDelete.cpp)
  LedgerCleanerImp::doLedger
      -> Node.cleaner_do_ledger (LedgerCleaner.cpp:273-330)
  LedgerMaster::makeFetchPack earliest-fetch gate
      -> Node.peer_fetch_pack (LedgerMaster.cpp:2140-2175)
"""

import hashlib

UINT32_MAX = 0xFFFFFFFF
LEDGER_CLOSE_MS = 4000
ACQUIRE_TIMEOUT_MS = 3000
ACQUIRE_TIMEOUTS_MAX = 6
PEER_COUNT_START = 5
PEER_COUNT_ADD = 3


def _h(label):
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _pseudo_hash(seq):
    """Stand-in ledger hash for sequence number seq."""
    return _h("postfiatd-ledger-%d" % seq)


def _latency_ms(peer_id, seq):
    """Deterministic peer response latency, 40-900 ms, always below the
    3000 ms acquire timeout when the peer holds the ledger."""
    return 40 + (int(_h("peer-%d-ledger-%d" % (peer_id, seq))[:8], 16) % 861)


class Peer:
    """A modelled peer. Holds ledgers [min_seq, tip]; anything below
    min_seq was pruned away (online delete) or never held."""

    def __init__(self, peer_id, min_seq, tip):
        self.peer_id = peer_id
        self.min_seq = min_seq
        self.tip = tip

    def holds(self, seq):
        return self.min_seq <= seq <= self.tip


class Node:
    """A modelled postfiatd node."""

    def __init__(self, config, peers, initial, log):
        self.cfg = dict(config)
        self.log = log  # list of log lines (strings)
        self.events = []  # list of event dicts
        self.clock_ms = 0
        self.peers = [Peer(p["id"], p["min_seq"], p["tip"])
                      for p in peers]
        self.ledger_history = self.cfg.get("ledger_history", 256)
        self.fetch_depth = self.cfg.get("fetch_depth", 1000000000)
        self.online_delete = self.cfg.get("online_delete", 0)
        self.advisory_delete = self.cfg.get("advisory_delete", False)
        self.delete_batch = self.cfg.get("delete_batch", 100)
        self.back_off_ms = self.cfg.get("back_off_ms", 100)
        self.age_threshold_s = self.cfg.get("age_threshold_s", 60)
        self.recovery_wait_s = self.cfg.get("recovery_wait_s", 5)
        self.earliest_seq = self.cfg.get("earliest_seq", 1)
        self.ledger_fetch_size = self.cfg.get("ledger_fetch_size", 2)
        self.tip = initial.get("tip", 1000)
        self.published = self.tip
        self.closed = self.tip
        self.last_rotated = initial.get("last_rotated", self.tip)
        self.can_delete = initial.get("can_delete", UINT32_MAX)
        self.minimum_online_ = initial.get("minimum_online", 0)
        self.mode = initial.get("mode", "FULL")
        self.validated_age_s = initial.get("validated_age_s", 0)
        self.age_override = None
        self.needs_network_ledger = False
        # Complete ledgers: modelled as a set; initial ranges given.
        self.complete = set()
        for lo, hi in initial.get("complete_ranges", [(1, self.tip)]):
            self.complete.update(range(lo, hi + 1))
        # SQL Ledgers table: seq -> hash. Initial rows given as ranges.
        self.sql = {}
        for lo, hi in initial.get("sql_ranges", [(1, self.tip)]):
            for s in range(lo, hi + 1):
                self.sql[s] = _pseudo_hash(s)
        # Node store: seqs whose objects exist.
        self.nodestore = set()
        for lo, hi in initial.get("nodestore_ranges",
                                  [(1, self.tip)]):
            self.nodestore.update(range(lo, hi + 1))
        # LedgerHistory cache: the in-memory cache starts with only the
        # validated ledger (the tip). A restarted node does not
        # repopulate it from SQL; everything else is reached through
        # the SQL fallback (loadByIndex / loadByHash), exactly as the
        # pinned code does on a cache miss. Validated ledgers are
        # added as the node validates (see validate_one).
        self.cache = {self.tip: _pseudo_hash(self.tip)}
        self.m_hist_ledger = None
        self.fill_in_progress = 0
        self.failures = set()  # mRecentFailures: hashes
        self.counters = {
            "rotations": 0,
            "sql_rows_deleted": 0,
            "sql_delete_batches": 0,
            "acquire_attempts": 0,
            "acquire_success": 0,
            "acquire_failed": 0,
            "acquire_timeouts": 0,
            "acquire_ms_total": 0,
            "fetch_packs_requested": 0,
            "fetch_packs_served": 0,
            "fetch_packs_refused": 0,
            "rpc_served": 0,
            "rpc_lgr_not_found": 0,
            "rpc_param_error": 0,
            "rpc_not_synced": 0,
            "rpc_acquiring": 0,
            "rpc_not_ready": 0,
            "backfill_acquired": 0,
            "backfill_failed": 0,
            "cleaner_cleaned": 0,
            "cleaner_failed": 0,
        }

    # -- logging ------------------------------------------------------
    def _log(self, msg):
        self.log.append("[seq %d t+%dms] %s" % (
            self.tip, self.clock_ms, msg))

    def _event(self, kind, seq, detail, value=None):
        self.events.append({"step_seq": self.tip, "clock_ms": self.clock_ms,
                            "event": kind, "seq": seq, "detail": detail,
                            "value": value})

    # -- config-derived values ---------------------------------------
    def _clamp_fetch_depth(self, fetch_depth):
        # SHAMapStoreImp.h:129 — online delete clamps fetch depth.
        if self.online_delete:
            return min(fetch_depth, self.online_delete)
        return fetch_depth

    def get_earliest_fetch(self):
        # LedgerMaster.cpp:637-650
        e = self.closed
        fd = self._clamp_fetch_depth(self.fetch_depth)
        if e > fd:
            e -= fd
        else:
            e = 0
        return e

    def minimum_online(self):
        # SHAMapStoreImp.cpp:711-720 — with online delete, the stored
        # floor; otherwise the minimum ledger in the SQL database.
        if self.online_delete and self.minimum_online_:
            return self.minimum_online_
        if self.sql:
            return min(self.sql)
        return None

    # -- hash / skip-list helpers ------------------------------------
    def _skip_hash(self, index):
        # hashOfSeq from the validated ledger (View.h:506-524): a
        # ledger contains the hashes of the 256 previous ledgers, and
        # every 0-mod-256 ledger is permanently enshrined in a
        # LedgerHashes page retrievable via the skip list. So the hash
        # is directly resolvable iff the index is within 256 below
        # the validated sequence, or is 0 mod 256 (any depth).
        if index < 1 or index > self.tip:
            return None
        if index == self.tip or (self.tip - index) <= 256 \
                or index % 256 == 0:
            return _pseudo_hash(index)
        return None

    @staticmethod
    def _candidate(index):
        # View.h:521-524 — (requested + 255) & (~255)
        return (index + 255) & (~255)

    def _walk_hash_by_seq(self, index, reason):
        # LedgerMaster.cpp:1663-1730
        if self.tip < index:
            return None
        h = self._skip_hash(index)
        if h:
            return h
        ref_index = self._candidate(index)
        ref_hash = self._skip_hash(ref_index)
        if not ref_hash:
            return None
        ledger = self.get_ledger_by_hash(ref_hash)
        if ledger is None:
            acquired = self.acquire(ref_hash, ref_index, reason)
            if acquired is None:
                return None
        # The candidate ledger's skip list covers the 256 ledgers
        # below it, so the requested hash is now resolvable.
        return _pseudo_hash(index)

    def _hash_for_history(self, index, reason):
        # LedgerMaster.cpp:1208-1228
        if self.m_hist_ledger is not None and \
                self.m_hist_ledger >= index:
            ret = self._skip_hash(index)
            if ret:
                return ret
            return self._walk_hash_by_seq(index, reason)
        return self._walk_hash_by_seq(index, reason)

    # -- ledger access ------------------------------------------------
    def get_ledger_by_hash(self, h):
        # LedgerHistory::getLedgerByHash (LedgerHistory.cpp:123-157):
        # cache, then load from the SQL database.
        for seq, hh in self.cache.items():
            if hh == h:
                return seq
        for seq, hh in self.sql.items():
            if hh == h:
                self.cache[seq] = h
                return seq
        return None

    def get_ledger_by_seq(self, index):
        # LedgerMaster::getLedgerBySeq (LedgerMaster.cpp:1730-1760)
        if index <= self.tip:
            h = self._skip_hash(index)
            if h:
                seq = self.get_ledger_by_hash(h)
                if seq is not None:
                    return seq
        seq = self._history_get_by_seq(index)
        if seq is not None:
            return seq
        if index == self.closed:
            return self.closed
        self._clear_ledger(index)
        return None

    def _history_get_by_seq(self, index):
        # LedgerHistory::getLedgerBySeq (LedgerHistory.cpp:86-122):
        # index map, then loadByIndex from the SQL database.
        if index in self.cache:
            return index
        if index in self.sql:
            self.cache[index] = self.sql[index]
            return index
        return None

    def _clear_ledger(self, seq):
        # LedgerMaster::clearLedger (LedgerMaster.cpp:514-517)
        self.complete.discard(seq)

    def _clear_prior_ledgers(self, seq):
        # LedgerMaster::clearPriorLedgers (LedgerMaster.cpp:1799-1804)
        self.complete = {s for s in self.complete if s >= seq}

    def _set_full_ledger(self, seq, is_current=False):
        # LedgerMaster::setFullLedger (LedgerMaster.cpp:826-860)
        self.cache[seq] = _pseudo_hash(seq)
        self.sql[seq] = _pseudo_hash(seq)
        self.nodestore.add(seq)
        self.complete.add(seq)
        if is_current:
            pass  # insert into history as validated (cache already set)

    # -- validation / rotation ---------------------------------------
    def validate_one(self):
        self.tip += 1
        self.published = self.tip
        self.closed = self.tip
        self.clock_ms += LEDGER_CLOSE_MS
        if self.age_override is None:
            self.validated_age_s = 0
        else:
            self.validated_age_s = self.age_override
        self._set_full_ledger(self.tip, is_current=True)
        self._on_ledger_closed()

    def _on_ledger_closed(self):
        # SHAMapStoreImp::onLedgerClosed + run() rotation gate
        # (SHAMapStoreImp.cpp:224-234, 331-344)
        if not self.online_delete:
            return
        if not self.last_rotated:
            self.last_rotated = self.tip
            return
        ready = (
            self.tip >= self.last_rotated + self.online_delete
            and self.can_delete >= self.last_rotated - 1
            and self._health_ok()
        )
        if ready:
            self._rotate()

    def _health_ok(self):
        # SHAMapStoreImp::healthWait (SHAMapStoreImp.cpp:680-690):
        # keep going only while FULL and validated age <= threshold.
        return (self.mode == "FULL"
                and self.validated_age_s <= self.age_threshold_s)

    def _rotate(self):
        old = self.last_rotated
        self._log("rotating validatedSeq %d lastRotated %d "
                  "deleteInterval %d canDelete_ %d state %s age %ds"
                  % (self.tip, old, self.online_delete,
                     self.can_delete, self.mode, self.validated_age_s))
        self._clear_prior(old)
        # copy the validated ledger's nodes (stand-in count: 128 nodes)
        node_count = 128
        self._log("copied ledger %d nodecount %d" % (self.tip, node_count))
        # freshen + clear caches at the new validated sequence
        self._clear_ledger_cache_prior(self.tip)
        self.last_rotated = self.tip
        self.counters["rotations"] += 1
        self._event("rotate", self.tip,
                    "lastRotated %d -> %d; minimumOnline %d"
                    % (old, self.tip, self.minimum_online_),
                    self.tip)

    def _clear_prior(self, last_rotated):
        # SHAMapStoreImp::clearPrior (SHAMapStoreImp.cpp:619-676)
        self.minimum_online_ = last_rotated + 1
        self._clear_prior_ledgers(last_rotated)
        # Only the Ledgers table is modelled row-for-row. The pinned
        # code clears the Transactions and AccountTransactions tables
        # with the same batched routine (SHAMapStoreImp.cpp:648-676);
        # their row counts are not modelled here.
        self._clear_sql(last_rotated, "Ledgers")

    def _clear_sql(self, last_rotated, table):
        # SHAMapStoreImp::clearSql (SHAMapStoreImp.cpp:560-600):
        # delete rows with LedgerSeq < lastRotated in delete_batch
        # batches, sleeping back_off between batches.
        rows = sorted(s for s in self.sql if s < last_rotated)
        if not rows:
            return
        lo = rows[0]
        batches = 0
        while lo < last_rotated:
            lo = min(last_rotated, lo + self.delete_batch)
            batches += 1
            if lo < last_rotated:
                self.clock_ms += self.back_off_ms
        for s in rows:
            del self.sql[s]
        if table == "Ledgers":
            self.counters["sql_rows_deleted"] += len(rows)
        self.counters["sql_delete_batches"] += batches
        self._log("finished deleting from: %s (%d rows, %d batches)"
                  % (table, len(rows), batches))

    def _clear_ledger_cache_prior(self, seq):
        # LedgerHistory::clearLedgerCachePrior (LedgerHistory.cpp:550-558)
        for s in [s for s in self.cache if s < seq]:
            del self.cache[s]

    # -- acquisition ---------------------------------------------------
    def acquire(self, h, seq, reason):
        # InboundLedgers::acquire (InboundLedgers.cpp:70-125)
        self.counters["acquire_attempts"] += 1
        if self.needs_network_ledger and reason not in ("GENERIC",
                                                        "CONSENSUS"):
            self._log("acquire %d refused: node needs network ledger" % seq)
            return None
        if h in self.failures:
            self.counters["acquire_failed"] += 1
            return None
        contacted = 0
        timeouts = 0
        total_ms = 0
        while True:
            # First attempt contacts PEER_COUNT_START peers; each
            # timeout adds PEER_COUNT_ADD more (InboundLedger.cpp:43-74).
            if timeouts == 0:
                batch = self.peers[0:PEER_COUNT_START]
            else:
                batch = self.peers[contacted:contacted + PEER_COUNT_ADD]
            contacted += len(batch)
            holders = [p for p in batch if p.holds(seq)]
            if holders:
                lat = min(_latency_ms(p.peer_id, seq) for p in holders)
                total_ms += lat
                self.counters["acquire_ms_total"] += total_ms
                self.counters["acquire_success"] += 1
                self._set_full_ledger(seq)
                self._log("acquired ledger %d from peer %d in %dms"
                          % (seq, holders[0].peer_id, total_ms))
                return seq
            total_ms += ACQUIRE_TIMEOUT_MS
            timeouts += 1
            self.counters["acquire_timeouts"] += 1
            self._log("acquire ledger %d timeout %d/%d"
                      % (seq, timeouts, ACQUIRE_TIMEOUTS_MAX))
            if timeouts > ACQUIRE_TIMEOUTS_MAX:
                # InboundLedger.cpp:376-390 — give up when timeouts_
                # exceeds 6, i.e. on the 7th timeout
                # (TimeoutCounter.cpp:95-112 increments first).
                self.failures.add(h)
                self.counters["acquire_failed"] += 1
                self.counters["acquire_ms_total"] += total_ms
                self._log("acquire ledger %d failed after %d timeouts"
                          % (seq, timeouts))
                return None
            # No more peers to add: further timeouts still elapse.

    def is_failure(self, h):
        return h in self.failures

    # -- history fetch / backfill --------------------------------------
    def fetch_for_history(self, missing, reason="HISTORY"):
        # LedgerMaster::fetchForHistory (LedgerMaster.cpp:1825-1915)
        h = self._hash_for_history(missing, reason)
        if not h:
            self._event("fetch_for_history", missing,
                        "no hash for missing ledger; nothing to acquire")
            return False
        seq = self.get_ledger_by_hash(h)
        if seq is not None:
            self._set_full_ledger(seq)
            self.m_hist_ledger = seq
            self._try_fill(seq)
            return True
        if self.is_failure(h):
            self._log("fetchForHistory found failed acquire %d" % missing)
            return False
        seq = self.acquire(h, missing, reason)
        if seq is not None:
            self.m_hist_ledger = seq
            self._try_fill(seq)
            return True
        if missing > self.earliest_seq:
            self._log("fetchForHistory want fetch pack %d" % missing)
            self._get_fetch_pack(missing, reason)
        return False

    def _get_fetch_pack(self, missing, reason):
        # Prefetch ledger_fetch_size_ ledgers below the missing one.
        self.counters["fetch_packs_requested"] += 1
        for i in range(self.ledger_fetch_size):
            seq = missing - i
            if seq <= 0:
                break
            h = self._skip_hash(seq)
            if h and self.get_ledger_by_hash(h) is None \
                    and not self.is_failure(h):
                self.acquire(h, seq, reason)

    def _try_fill(self, seq):
        # LedgerMaster::tryFill (LedgerMaster.cpp:651-720): walk
        # backwards while the SQL database has hashes and the node
        # store has the objects; mark the range complete.
        lo = seq
        cur = seq
        while cur > 1:
            prev = cur - 1
            if prev in self.sql and prev in self.nodestore:
                lo = prev
                cur = prev
            else:
                break
        for s in range(lo, seq + 1):
            self.complete.add(s)
        if lo < seq:
            self._log("tryFill marked complete %d-%d" % (lo, seq))

    def backfill(self):
        # LedgerMaster::doAdvance history branch
        # (LedgerMaster.cpp:1945-1998): while in sync, find the
        # highest missing ledger below the published tip and try to
        # acquire it when shouldAcquire allows it.
        while True:
            below = [s for s in range(self.earliest_seq, self.published)
                     if s not in self.complete]
            if not below:
                return "complete"
            missing = max(below)
            mo = self.minimum_online()
            if not self.should_acquire(missing):
                self._event("backfill_halt", missing,
                            "shouldAcquire refused: outside ledger_history "
                            "window and below minimumOnline %s" % mo, mo)
                self.counters["backfill_failed"] += 1
                return "gate-refused"
            ok = self.fetch_for_history(missing, "HISTORY")
            if ok:
                self.counters["backfill_acquired"] += 1
            else:
                self.counters["backfill_failed"] += 1
                self._event("backfill_halt", missing,
                            "fetchForHistory failed; gap remains")
                return "fetch-failed"

    def should_acquire(self, candidate):
        # LedgerMaster::shouldAcquire (LedgerMaster.cpp:75-99)
        current = self.tip
        if candidate >= current:
            return True
        if current - candidate <= self.ledger_history:
            return True
        mo = self.minimum_online()
        if mo is not None and candidate >= mo:
            return True
        return False

    # -- RPC ------------------------------------------------------------
    def rpc_ledger(self, index=None, hash_hex=None, seq=None,
                   api_version=2):
        # RPC getLedgerByContext (RPCHelpers.cpp:1030-1145)
        if (index is None) == (hash_hex is None):
            self.counters["rpc_param_error"] += 1
            return ("param_error",
                    "Exactly one of ledger_hash and ledger_index can be set.")
        if hash_hex is not None:
            # A hash-only request carries no sequence; the harness
            # supplies the sequence the caller believes it has, as a
            # stand-in for the peer's ledger-hash index.
            h = hash_hex
        else:
            if self.validated_age_s > 120:  # Tuning.h:65, 2 minutes
                self.counters["rpc_not_synced"] += 1
                return ("not_synced", "rpcNOT_SYNCED"
                        if api_version != 1 else "rpcNO_CURRENT")
            if index >= self.tip:
                self.counters["rpc_param_error"] += 1
                return ("param_error", "Ledger index too large")
            if index <= 0:
                self.counters["rpc_param_error"] += 1
                return ("param_error", "Ledger index too small")
            h = self._skip_hash(index)
            if not h:
                ref_index = self._candidate(index)
                ref_hash = self._skip_hash(ref_index)
                ref = self.get_ledger_by_hash(ref_hash) \
                    if ref_hash else None
                if ref is None and ref_hash:
                    ref = self.acquire(ref_hash, ref_index, "GENERIC")
                if ref is None:
                    self.counters["rpc_lgr_not_found"] += 1
                    return ("lgr_not_found",
                            "acquiring ledger containing requested index")
                # The candidate ledger's skip list covers the 256
                # ledgers below it, so the requested hash is resolved.
                h = _pseudo_hash(index)
            seq = index
        # Try to acquire the desired ledger (always attempted by RPC).
        held = self.get_ledger_by_hash(h)
        if held is not None:
            self.counters["rpc_served"] += 1
            return ("served", held)
        got = self.acquire(h, seq if seq is not None else 0, "GENERIC")
        if got is not None:
            self.counters["rpc_served"] += 1
            return ("served", got)
        # In the pinned code, a null acquire falls through to find():
        # if an InboundLedger is still in progress, its JSON is
        # returned ("acquiring"); otherwise rpcNOT_READY. The
        # synchronous simulator never has an in-progress acquire, so
        # a failed acquire is lgr_not_found here. See
        # docs/environment.md, limitation L3.
        self.counters["rpc_lgr_not_found"] += 1
        return ("lgr_not_found", "lgrNotFound")

    def rpc_can_delete(self, arg):
        # RPC doCanDelete (CanDelete.cpp): advisory delete only.
        if not self.advisory_delete:
            return ("not_enabled", "rpcNOT_ENABLED")
        if isinstance(arg, int):
            seq = arg
        elif arg == "never":
            seq = 0
        elif arg == "always":
            seq = UINT32_MAX
        elif arg == "now":
            seq = self.last_rotated
            if not seq:
                return ("not_ready", "rpcNOT_READY")
        elif isinstance(arg, str):
            seq = self.get_ledger_by_hash(arg)
            if seq is None:
                return ("lgr_not_found", "ledgerNotFound")
        else:
            return ("invalid_params", "rpcINVALID_PARAMS")
        self.can_delete = seq
        self._log("can_delete set to %d" % seq)
        return ("ok", seq)

    def peer_fetch_pack(self, have_seq):
        # LedgerMaster::makeFetchPack earliest-fetch gate
        # (LedgerMaster.cpp:2140-2175)
        self.counters["fetch_packs_requested"] += 1
        have = self.get_ledger_by_seq(have_seq)
        if have is None:
            self.counters["fetch_packs_refused"] += 1
            return ("refused", "peer requests fetch pack for ledger "
                    "we don't have")
        if have_seq < self.get_earliest_fetch():
            self.counters["fetch_packs_refused"] += 1
            return ("refused", "peer requests fetch pack that is too "
                    "early")
        self.counters["fetch_packs_served"] += 1
        return ("served", have_seq)

    # -- ledger cleaner --------------------------------------------------
    def cleaner_do_ledger(self, seq):
        # LedgerCleanerImp::doLedger (LedgerCleaner.cpp:273-330)
        h = _pseudo_hash(seq)
        node_ledger = self.acquire(h, seq, "GENERIC")
        if node_ledger is None:
            self._clear_ledger(seq)
            self.acquire(h, seq, "GENERIC")  # retry, as the code does
            self.counters["cleaner_failed"] += 1
            self._log("cleaner: ledger %d not available" % seq)
            return False
        db_ledger = self.sql.get(seq)
        if db_ledger is None or db_ledger != h:
            # Mismatch with the SQL database: re-save transactions.
            self.sql[seq] = h
            self.nodestore.add(seq)
            self._log("cleaner: ledger %d mismatches SQL DB; re-saved"
                      % seq)
        if seq not in self.nodestore:
            self._clear_ledger(seq)
            self.acquire(h, seq, "GENERIC")
            self.counters["cleaner_failed"] += 1
            self._log("cleaner: ledger %d is missing nodes" % seq)
            return False
        self.counters["cleaner_cleaned"] += 1
        return True

    # -- reporting -------------------------------------------------------
    def validated_range(self):
        # LedgerMaster::getFullValidatedRange (LedgerMaster.cpp:569-590)
        max_val = self.published
        if not max_val:
            return (None, None)
        below = [s for s in range(1, max_val) if s not in self.complete]
        if not below:
            return (max_val, max_val)
        return (max(below) + 1, max_val)

    def complete_ledgers_str(self):
        # LedgerMaster::getCompleteLedgers (LedgerMaster.cpp:1615-1620)
        if not self.complete:
            return ""
        parts = []
        run_start = None
        prev = None
        for s in sorted(self.complete):
            if run_start is None:
                run_start = prev = s
            elif s == prev + 1:
                prev = s
            else:
                parts.append("%d-%d" % (run_start, prev)
                             if prev > run_start else "%d" % run_start)
                run_start = prev = s
        parts.append("%d-%d" % (run_start, prev)
                     if prev > run_start else "%d" % run_start)
        return ",".join(parts)

    def summary(self):
        lo, hi = self.validated_range()
        return {
            "tip": self.tip,
            "published": self.published,
            "last_rotated": self.last_rotated,
            "can_delete": self.can_delete,
            "minimum_online": self.minimum_online(),
            "sql_min": min(self.sql) if self.sql else None,
            "sql_max": max(self.sql) if self.sql else None,
            "sql_rows": len(self.sql),
            "cache_entries": len(self.cache),
            "complete_ledgers": self.complete_ledgers_str(),
            "validated_range": [lo, hi],
            "get_earliest_fetch": self.get_earliest_fetch(),
            "clamped_fetch_depth":
                self._clamp_fetch_depth(self.fetch_depth),
            "counters": dict(self.counters),
        }
