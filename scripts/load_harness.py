#!/usr/bin/env python3
"""load_harness.py — run one pruning scenario and write unedited outputs.

Usage: python3 scripts/load_harness.py scenarios/S1-*.json

Reads a scenario definition, drives scripts/simulator.py through its
steps, and writes three outputs named after the scenario id (for
example, scenario S1-aggressive-pruning writes):
  outputs/S1-aggressive-pruning.json  — full result (config, peers,
                       steps, final state, counters, events,
                       per-request rows)
  outputs/S1-aggressive-pruning.csv   — one row per measured request
  outputs/S1-aggressive-pruning.log   — the simulator's own log lines,
                       unedited

Every number in the outputs comes from this script's run. Nothing is
hand-edited afterwards; digests are computed over the files as written.
"""

import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from simulator import Node, _pseudo_hash, LEDGER_CLOSE_MS  # noqa: E402

PINNED_COMMIT = "0085a1ff885d6a446369cf73a4430f75af22be55"


def run_scenario(path):
    with open(path, "r", encoding="utf-8") as f:
        scen = json.load(f)
    log = []
    node = Node(scen["config"], scen["peers"], scen["initial"], log)
    rows = []
    step_results = []
    for i, step in enumerate(scen["steps"]):
        op = step["op"]
        before_ms = node.counters["acquire_ms_total"]
        res = {"step": i, "op": op}
        if op == "validate":
            n = step["count"]
            node._log("validating %d ledgers" % n)
            for _ in range(n):
                node.validate_one()
            res.update({"validated": n, "tip": node.tip,
                        "last_rotated": node.last_rotated,
                        "rotations": node.counters["rotations"]})
        elif op == "set_age":
            node.validated_age_s = step["seconds"]
            res.update({"validated_age_s": step["seconds"]})
        elif op == "set_age_override":
            node.age_override = step["seconds"]
            res.update({"age_override": step["seconds"]})
        elif op == "set_mode":
            node.mode = step["mode"]
            res.update({"mode": step["mode"]})
        elif op == "set_needs_network":
            node.needs_network_ledger = step["value"]
            res.update({"needs_network_ledger": step["value"]})
        elif op == "set_fetch_depth":
            # Stands in for a second node started with a different
            # [fetch_depth]; the clamp arithmetic is the same function
            # (SHAMapStoreImp.h:129). See the scenario file's notes.
            node.fetch_depth = step["value"]
            res.update({"fetch_depth": step["value"],
                        "clamped_fetch_depth":
                            node._clamp_fetch_depth(step["value"]),
                        "get_earliest_fetch": node.get_earliest_fetch()})
        elif op == "rpc_fetch_both":
            # Both ledger_hash and ledger_index set: the pinned code
            # rejects this before any other check (RPCHelpers.cpp).
            outcome, detail = node.rpc_ledger(
                index=step["seq"], hash_hex=_pseudo_hash(step["seq"]),
                api_version=step.get("api_version", 2))
            rows.append({"scenario": scen["id"], "op": "rpc_fetch_both",
                         "kind": "both", "seq": step["seq"],
                         "outcome": outcome, "detail": detail,
                         "acquire_ms": 0,
                         "api_version": step.get("api_version", 2)})
            res.update({"seq": step["seq"], "outcome": outcome,
                        "detail": detail})
        elif op == "rpc_fetch":
            kind = step.get("kind", "index")
            api_version = step.get("api_version", 2)
            outcomes = {}
            for seq in step["seqs"]:
                ms0 = node.counters["acquire_ms_total"]
                if kind == "hash":
                    outcome, detail = node.rpc_ledger(
                        hash_hex=_pseudo_hash(seq), seq=seq,
                        api_version=api_version)
                else:
                    outcome, detail = node.rpc_ledger(
                        index=seq, api_version=api_version)
                ms = node.counters["acquire_ms_total"] - ms0
                outcomes.setdefault(outcome, 0)
                outcomes[outcome] += 1
                rows.append({"scenario": scen["id"], "op": "rpc_fetch",
                             "kind": kind, "seq": seq,
                             "outcome": outcome, "detail": detail,
                             "acquire_ms": ms,
                             "api_version": api_version})
            res.update({"kind": kind, "requested": len(step["seqs"]),
                        "outcomes": outcomes})
        elif op == "backfill":
            outcome = node.backfill()
            res.update({"outcome": outcome,
                        "acquired": node.counters["backfill_acquired"],
                        "failed": node.counters["backfill_failed"]})
        elif op == "can_delete":
            arg = step["arg"]
            if isinstance(arg, dict) and "hash_seq" in arg:
                # The scenario names a ledger by sequence; the hash is
                # the deterministic stand-in hash for that sequence.
                arg = _pseudo_hash(arg["hash_seq"])
            outcome, detail = node.rpc_can_delete(arg)
            res.update({"arg": step["arg"], "outcome": outcome,
                        "value": detail})
        elif op == "clean":
            results = {}
            for seq in step["seqs"]:
                ok = node.cleaner_do_ledger(seq)
                results[seq] = "cleaned" if ok else "failed"
                rows.append({"scenario": scen["id"], "op": "clean",
                             "kind": "", "seq": seq,
                             "outcome": results[seq], "detail": "",
                             "acquire_ms": 0, "api_version": ""})
            res.update({"results": results})
        elif op == "corrupt":
            what = step["what"]
            for seq in step["seqs"]:
                if what == "nodes":
                    node.nodestore.discard(seq)
                    node._log("corrupted ledger %d: nodes removed "
                              "from node store" % seq)
                elif what == "sql":
                    node.sql[seq] = "0" * 64
                    node._log("corrupted ledger %d: SQL row hash "
                              "replaced with zeros" % seq)
            res.update({"what": what, "seqs": step["seqs"]})
        elif op == "fetch_pack":
            outcomes = {}
            for root in step["roots"]:
                outcome, detail = node.peer_fetch_pack(root)
                outcomes.setdefault(outcome, 0)
                outcomes[outcome] += 1
                rows.append({"scenario": scen["id"], "op": "fetch_pack",
                             "kind": "", "seq": root,
                             "outcome": outcome, "detail": detail,
                             "acquire_ms": 0, "api_version": ""})
            res.update({"roots": step["roots"], "outcomes": outcomes,
                        "get_earliest_fetch": node.get_earliest_fetch(),
                        "clamped_fetch_depth":
                            node._clamp_fetch_depth(node.fetch_depth)})
        else:
            raise ValueError("unknown op %r in %s" % (op, path))
        res["acquire_ms_step"] = \
            node.counters["acquire_ms_total"] - before_ms
        step_results.append(res)
    summary = node.summary()
    result = {
        "scenario_id": scen["id"],
        "title": scen["title"],
        "severity": scen["severity"],
        "severity_reason": scen["severity_reason"],
        "pinned_commit": PINNED_COMMIT,
        "simulated": True,
        "config": scen["config"],
        "peers": scen["peers"],
        "initial": scen["initial"],
        "steps": step_results,
        "rows": rows,
        "events": node.events,
        "final": summary,
    }
    return scen["id"], result, log, rows


def main(argv):
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    outdir = os.path.join(base, "outputs")
    os.makedirs(outdir, exist_ok=True)
    for path in argv[1:]:
        sid, result, log, rows = run_scenario(path)
        json_path = os.path.join(outdir, sid + ".json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, sort_keys=True)
            f.write("\n")
        csv_path = os.path.join(outdir, sid + ".csv")
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f, fieldnames=["scenario", "op", "kind", "seq",
                               "outcome", "detail", "acquire_ms",
                               "api_version"])
            w.writeheader()
            w.writerows(rows)
        log_path = os.path.join(outdir, sid + ".log")
        with open(log_path, "w", encoding="utf-8") as f:
            for line in log:
                f.write(line + "\n")
        print("%s: %d rows, %d events, tip %d, sql_rows %d, "
              "rotations %d" % (
                  sid, len(rows), len(result["events"]),
                  result["final"]["tip"], result["final"]["sql_rows"],
                  result["final"]["counters"]["rotations"]))


if __name__ == "__main__":
    main(sys.argv)
