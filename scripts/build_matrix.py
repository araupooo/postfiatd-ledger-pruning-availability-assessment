#!/usr/bin/env python3
"""build_matrix.py — build the severity-ranked scenario matrix from the
unedited scenario outputs.

Usage: python3 scripts/build_matrix.py

Reads outputs/S*.json (written by scripts/load_harness.py) and writes:
  outputs/matrix.json — one entry per scenario with measured counts
  outputs/matrix.csv  — the same, one row per scenario

The matrix is derived, never hand-edited. Severity is assigned in the
scenario definition; this script ranks by severity (CRITICAL > HIGH >
MEDIUM > LOW > INFO) and attaches the measured numbers.
"""

import csv
import json
import os

RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


def main():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    outdir = os.path.join(base, "outputs")
    entries = []
    for name in sorted(os.listdir(outdir)):
        if not name.endswith(".json") or not name.startswith("S"):
            continue
        with open(os.path.join(outdir, name), "r",
                  encoding="utf-8") as f:
            r = json.load(f)
        rows = r["rows"]
        rpc = [x for x in rows if x["op"] == "rpc_fetch"]
        served = sum(1 for x in rpc if x["outcome"] == "served")
        failed = sum(1 for x in rpc if x["outcome"] != "served")
        packs = [x for x in rows if x["op"] == "fetch_pack"]
        packs_served = sum(1 for x in packs if x["outcome"] == "served")
        packs_refused = sum(1 for x in packs
                            if x["outcome"] == "refused")
        cleans = [x for x in rows if x["op"] == "clean"]
        cleaned = sum(1 for x in cleans if x["outcome"] == "cleaned")
        clean_failed = sum(1 for x in cleans if x["outcome"] == "failed")
        c = r["final"]["counters"]
        entries.append({
            "scenario_id": r["scenario_id"],
            "title": r["title"],
            "severity": r["severity"],
            "severity_reason": r["severity_reason"],
            "rpc_requested": len(rpc),
            "rpc_served": served,
            "rpc_failed": failed,
            "fetch_packs_served": packs_served,
            "fetch_packs_refused": packs_refused,
            "cleaned": cleaned,
            "clean_failed": clean_failed,
            "rotations": c["rotations"],
            "sql_rows_deleted": c["sql_rows_deleted"],
            "sql_delete_batches": c["sql_delete_batches"],
            "acquire_attempts": c["acquire_attempts"],
            "acquire_success": c["acquire_success"],
            "acquire_failed": c["acquire_failed"],
            "acquire_timeouts": c["acquire_timeouts"],
            "acquire_ms_total": c["acquire_ms_total"],
            "backfill_acquired": c["backfill_acquired"],
            "backfill_failed": c["backfill_failed"],
            "final_tip": r["final"]["tip"],
            "final_sql_min": r["final"]["sql_min"],
            "final_sql_rows": r["final"]["sql_rows"],
            "final_minimum_online": r["final"]["minimum_online"],
            "final_validated_range": r["final"]["validated_range"],
            "final_complete_ledgers": r["final"]["complete_ledgers"],
            "final_get_earliest_fetch": r["final"]["get_earliest_fetch"],
        })
    entries.sort(key=lambda e: (RANK[e["severity"]], e["scenario_id"]))
    with open(os.path.join(outdir, "matrix.json"), "w",
              encoding="utf-8") as f:
        json.dump(entries, f, indent=2, sort_keys=True)
        f.write("\n")
    fields = ["scenario_id", "title", "severity", "severity_reason",
              "rpc_requested", "rpc_served", "rpc_failed",
              "fetch_packs_served", "fetch_packs_refused", "cleaned",
              "clean_failed", "rotations", "sql_rows_deleted",
              "sql_delete_batches", "acquire_attempts",
              "acquire_success", "acquire_failed", "acquire_timeouts",
              "acquire_ms_total", "backfill_acquired",
              "backfill_failed", "final_tip", "final_sql_min",
              "final_sql_rows", "final_minimum_online",
              "final_validated_range", "final_complete_ledgers",
              "final_get_earliest_fetch"]
    with open(os.path.join(outdir, "matrix.csv"), "w",
              encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for e in entries:
            row = dict(e)
            row["final_validated_range"] = "%s-%s" % tuple(
                e["final_validated_range"])
            w.writerow(row)
    for e in entries:
        print("%s %-8s rpc %d/%d served, timeouts %d, rotations %d, "
              "backfill +%d" % (
                  e["scenario_id"], e["severity"], e["rpc_served"],
                  e["rpc_requested"], e["acquire_timeouts"],
                  e["rotations"], e["backfill_acquired"]))


if __name__ == "__main__":
    main()
