# Methodology

## Approach

1. **Pin the commit.** postfiatd `0085a1ff885d6a446369cf73a4430f75af22be55`
   (2026-10-10), the same commit used by the earlier packs in this
   series. All 22 cited source files were verified blob-by-blob
   against the GitHub API tree for that commit (22/22 agree); line
   numbers were read with `grep -n` / `sed -n` on the local checkout.
   See `docs/source-inventory.md`.
2. **Read the pruning, retention, fetch, and sync code first.** The
   inventory covers config parsing, online delete, the rotation gate,
   `shouldAcquire`, the history backfill, the skip list, inbound
   acquisition, RPC resolution, `can_delete`, the ledger cleaner, and
   the fetch-pack gate — with exact file-and-line citations.
3. **Build a faithful protocol-level simulator** (`scripts/simulator.py`)
   that re-implements the cited decision logic, with every control
   parameter taken verbatim from the pinned code. No real build was
   attempted (see `docs/environment.md`, L1).
4. **Define 11 scenarios** (`scenarios/S0-*.json` … `S10-*.json`)
   covering aggressive pruning, partial-history nodes, pruned-range
   fetches, backfill from pruned and full peers, advisory
   `can_delete`, cleaner repair, the RPC resolution matrix, the
   fetch-depth clamp, and deferred rotation. Each scenario states its
   severity and its reasoning in the file itself.
5. **Run everything through scripts.** `scripts/load_harness.py`
   runs one scenario and writes unedited `outputs/S1-aggressive-pruning.json`,
   `.csv`, and `.log` (one triple per scenario id). `scripts/build_matrix.py` builds the
   severity-ranked matrix from those outputs.
   `scripts/measure_controls.py` measures each inventoried control
   against the outputs. Nothing is hand-edited afterwards.
6. **Verify reproducibility.** `scripts/run_all.sh` reruns the whole
   pipeline (exit 0). `scripts/make_sha256sums.sh` and
   `scripts/verify_digests.sh` digest-check every committed file.
   `scripts/make_reproduction_transcript.py` reproduces the pack
   from a fresh copy and commits the transcript
   (`outputs/fresh-clone-reproduction.log`).

## Labels

- **OBSERVED** — a behaviour read directly from the pinned source
  (file-and-line cited). No scenario output is OBSERVED in the sense
  of a live node run, because no live node was run.
- **SIMULATED** — every measured number in `outputs/`: produced by
  the simulator from the pinned parameters. The numbers are exact
  outputs of the modeled logic, not estimates, but they are
  measurements of the model, not of a running postfiatd.
- **UNMEASURED** — a control whose source citation is exact but no
  scenario exercised it (C16, C17). Stated plainly in
  `outputs/controls.json` and `docs/control-inventory.md`.

## Model bugs found and fixed during the build

The simulator was wrong in five places before the final run. Each was
caught by checking the simulator's output against the pinned code,
not by adjusting the code to fit a preferred result. The fixes are
recorded here so a reviewer can see what changed and why.

1. **History cache pre-populated with the whole window (fixed).**
   The first version built the LedgerHistory cache as the last 256
   ledgers below the tip, regardless of what the node actually held.
   In the first S4 run this made 255 ledgers appear "already held":
   the backfill counted 742 acquired ledgers with only 487 successful
   acquires. The pinned code populates the cache only by inserting
   validated ledgers; a restarted node starts with (at most) the
   validated ledger. Fixed: the cache starts with the tip only, and
   everything else is reached through the SQL fallback, as on a
   restarted node. After the fix S4 acquires exactly 742 ledgers with
   742 successful acquires plus 1 failed acquire.
2. **`minimum_online` name collision (fixed).** The attribute holding
   the stored floor and the method computing the floor shared the
   name `minimum_online`, so `summary()` crashed with
   `TypeError: 'int' object is not callable`. Fixed: the attribute is
   `minimum_online_`, the method stays `minimum_online()`.
3. **Timeout off-by-one in the prose (fixed).** The code gives up
   when `timeouts_ > ledgerTimeoutRetriesMax` (6), and
   `TimeoutCounter::invokeOnTimer` increments `timeouts_` before
   calling `onTimer` — so a failed acquire burns **7** timeouts
   (21,000 ms), not 6 (18,000 ms). The simulator already did this
   (its loop fails when `timeouts > 6`); the scenario notes and the
   control measurements said 6. Fixed in the notes, the severity
   reasons, and C06.
4. **Rotation sets `lastRotated` to the current tip (found, not a
   bug).** The first hand-prediction assumed a rotation at the gate
   threshold (e.g. 1256). The pinned code sets `lastRotated` to the
   current validated sequence (`state_db_.setLastRotated(validatedSeq)`),
   so a rotation delayed by `can_delete` fires late and shifts the
   next interval. S6 measured this: rotations at 1301, 1601, 1901,
   2157 — not at 1256, 1512, 1768, 2024. The simulator was already
   correct; the scenario notes and C00/C01 were corrected to match
   the measured behaviour.
5. **Backfill cannot extend below the SQL minimum without a floor
   (found, not a bug).** The first S4/S5 design assumed the backfill
   would descend 742 ledgers to a pruned peer's boundary with online
   delete off. It stopped after 256: `shouldAcquire`'s third
   disjunct uses `minimumOnline()`, which without online delete is
   `minSqlSeq()` — the SQL minimum — and the SQL minimum can never
   be extended below itself by backfill. The scenarios were redesigned
   around an online-delete floor (`minimumOnline_ = 1257`): S4 now
   descends past the window to the floor and fails on the floor
   ledger itself; S5 reaches the floor with a full peer. The finding
   is recorded in `docs/findings-report.md` (F3).
6. **Candidate-ledger arithmetic (found, not a bug).** The first
   hand-prediction said the candidate for ledger 1005 was 1280.
   `(1005 + 255) & (~255)` is 1024, not 1280 — 1024 is the next
   multiple of 256 at or above 1005. The simulator was already
   correct; the predictions were corrected. This matters for S2: the
   candidate for 1000, 1005, 1010, and 1020 is 1024, which the node
   does not hold, so those four requests fail at the candidate step.
7. **`hashOfSeq` does not resolve arbitrary indices (found, not a
   bug).** The first simulator version resolved any index at or below
   the tip. The pinned code (`View.h:495-524`) resolves only indices
   within 256 below the ledger sequence or 0 mod 256. Fixed: the
   skip-list rule is modeled exactly, and the candidate-ledger path
   is exercised by S2 and S3.

## Determinism

- No wall clock, no `random` module. All pseudo-randomness comes from
  SHA-256 of stable labels. Virtual time advances only by ledger
  closes (4000 ms) and modeled sleeps (back-off 100 ms, acquire
  timeouts 3000 ms).
- `run_all.sh` runs the pipeline twice in the transcript
  reproduction; the second run's outputs are byte-identical to the
  committed ones except `outputs/run_all.log`, which is excluded from
  `SHA256SUMS` and from the manifest as a run artifact.
- `PYTHONDONTWRITEBYTECODE=1` is set in `run_all.sh` so no
  `__pycache__` timestamps leak into the pack.
