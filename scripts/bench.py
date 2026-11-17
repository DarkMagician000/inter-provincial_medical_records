#!/usr/bin/env python3
"""Measure Q1-Q5 and N1/N4/N5; run --self-test without a database."""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import psycopg

ROOT = Path(__file__).resolve().parents[1]
SITES = ("tayninh", "hcm", "cantho", "dongnai")
TABLES = (
    "hospital", "drug", "patient", "visit", "prescription", "visit_cardio",
    "visit_eye", "visit_blood", "visit_eye_diagnosis", "visit_blood_test",
)
RELATIONAL = (
    "visit_cardio", "visit_eye", "visit_eye_diagnosis", "visit_blood", "visit_blood_test",
)
CONTAINMENT = """SELECT count(*) FROM public.visit
                 WHERE result @> '{"ecg":{"rhythm":"afib"}}'"""


def connect(config: dict, site: str, *, readonly: bool = True) -> psycopg.Connection:
    """Open a direct, unprepared connection to a configured site."""
    import psycopg

    endpoint = config["ref"] if site == "ref" else config["sites"][site]
    return psycopg.connect(
        host=endpoint["ip"], port=endpoint["port"], dbname=config["dbname"],
        user="postgres", connect_timeout=10, autocommit=True, prepare_threshold=None,
        options=f"-c default_transaction_read_only={'on' if readonly else 'off'}",
    )


def walk_plan(plan: dict) -> Iterator[dict]:
    """Yield a JSON EXPLAIN plan and all its child nodes."""
    yield plan
    for child in plan.get("Plans", []):
        yield from walk_plan(child)


def plan_metrics(plan: dict) -> tuple[int, float]:
    """Return executed site count and foreign Actual Rows times Actual Loops."""
    sites = set()
    foreign_rows = 0.0
    for node in walk_plan(plan):
        loops = node["Actual Loops"]
        if not loops:
            continue
        kind = node["Node Type"].removeprefix("Parallel ").removeprefix("Async ")
        if kind in {"Foreign Scan", "Foreign Join"}:
            remote = set(re.findall(
                r'(?<![\w])"?(hcm|cantho|dongnai)"?\s*\.', node.get("Relations", ""),
            ))
            if node.get("Schema") in SITES[1:]:
                remote.add(node["Schema"])
            if not remote:
                raise ValueError(f"Cannot identify foreign site in EXPLAIN node: {node}")
            sites.update(remote)
            foreign_rows += node["Actual Rows"] * loops
        elif node.get("Schema") == "public" and node.get("Relation Name") and kind in {
            "Seq Scan", "Index Scan", "Index Only Scan", "Bitmap Heap Scan",
            "Tid Scan", "Tid Range Scan", "Sample Scan",
        }:
            sites.add("tayninh")
    return len(sites), foreign_rows


def measure(cursor: psycopg.Cursor, query: str, runs: int) -> tuple[list[float], list[tuple]]:
    """Time execute plus fetchall in milliseconds; retain the final result."""
    if runs < 2:
        raise ValueError("At least two runs are required to discard the warm-up")
    timings = []
    result = []
    for run in range(runs):
        started = perf_counter()
        cursor.execute(query)
        rows = cursor.fetchall()
        timings.append((perf_counter() - started) * 1000)
        if run and len(rows) != len(result):
            raise RuntimeError("Query row count changed between runs; stop concurrent writes")
        result = rows
    return timings, result


def timing_fields(timings: list[float]) -> dict[str, float]:
    """Format all runs and the median excluding the first run."""
    return {
        "median_ms": round(median(timings[1:]), 6),
        **{f"run{number}_ms": round(value, 6) for number, value in enumerate(timings, 1)},
    }


def write_csv(destination: Path, fields: list[str], rows: list[dict]) -> None:
    """Replace a result CSV only after the complete new file is written."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".csv.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def set_delay(milliseconds: int) -> None:
    """Apply remote-only delay, sending tc diagnostics to stderr."""
    arguments = ["off"] if milliseconds == 0 else ["on", str(milliseconds)]
    subprocess.run(
        ["bash", str(ROOT / "scripts/delay.sh"), *arguments],
        cwd=ROOT, check=True, stdout=sys.stderr,
    )


def inventory(config: dict) -> tuple[list[dict], list[dict]]:
    """Count ten tables directly on five databases and cross-region visits on four sites."""
    fragments, crossregion = [], []
    for site in (*SITES, "ref"):
        with connect(config, site) as connection, connection.cursor() as cursor:
            for table in TABLES:
                cursor.execute(f'SELECT count(*) FROM public."{table}"')
                fragments.append({"site": site, "table": table, "rows": cursor.fetchone()[0]})
            if site == "ref":
                continue
            cursor.execute("""
                SELECT count(*),
                       count(*) FILTER (WHERE hospital.province <> patient.home_province),
                       count(*) FILTER (WHERE hospital.hospital_id IS NULL
                           OR patient.patient_id IS NULL OR hospital.province IS NULL
                           OR patient.home_province IS NULL)
                FROM public.visit
                LEFT JOIN public.hospital USING (hospital_id)
                LEFT JOIN public.patient USING (patient_id)
            """)
            visits, cross, invalid = cursor.fetchone()
            if invalid:
                raise ValueError(f"{site}: {invalid} visits lack a hospital/patient province")
            crossregion.append({
                "site": site, "visits": visits, "cross_region_visits": cross,
                "pct": round(100 * cross / visits, 6) if visits else 0.0,
            })
    return fragments, crossregion


def storage_measurements(config: dict, runs: int) -> tuple[list[dict], list[dict]]:
    """Measure reference storage and containment timings; roll back both trial GIN indexes."""
    storage, timings = [], []
    with connect(config, "ref", readonly=False) as connection:
        with connection.transaction(force_rollback=True), connection.cursor() as cursor:
            cursor.execute("""
                SELECT indexrelid::regclass::text
                FROM pg_index
                JOIN pg_class ON pg_class.oid = indexrelid
                JOIN pg_am ON pg_am.oid = pg_class.relam
                WHERE indrelid = 'public.visit'::regclass AND amname = 'gin'
            """)
            existing = cursor.fetchall()
            if existing:
                raise ValueError(f"ref.visit already has GIN indexes; baseline is not index-free: {existing}")
            cursor.execute("ANALYZE public.visit")
            cursor.execute("SELECT coalesce(sum(pg_column_size(result)), 0) FROM public.visit")
            sizes = {"jsonb_column_total": cursor.fetchone()[0]}
            for table in ("visit", *RELATIONAL):
                cursor.execute("SELECT pg_total_relation_size(%s::regclass)", (f"public.{table}",))
                sizes[f"{table}_total"] = cursor.fetchone()[0]
            sizes["relational_total"] = sum(sizes[f"{table}_total"] for table in RELATIONAL)
            for variant in ("none", "jsonb_ops", "jsonb_path_ops"):
                if variant != "none":
                    column = "result" if variant == "jsonb_ops" else "result jsonb_path_ops"
                    cursor.execute(f"CREATE INDEX tmp_gin ON public.visit USING gin ({column})")
                    cursor.execute("SELECT pg_relation_size('public.tmp_gin')")
                    sizes[f"gin_{variant}"] = cursor.fetchone()[0]
                elapsed, rows = measure(cursor, CONTAINMENT, runs)
                cursor.execute("EXPLAIN (ANALYZE, VERBOSE, FORMAT JSON) " + CONTAINMENT)
                plan = cursor.fetchone()[0][0]["Plan"]
                used = any(node.get("Index Name") == "tmp_gin" for node in walk_plan(plan))
                if variant != "none" and not used:
                    print(f"Warning: optimizer did not use {variant}; timing is its chosen plan", file=sys.stderr)
                timings.append({
                    "index": variant, **timing_fields(elapsed),
                    "matched_visits": rows[0][0], "index_used": used,
                })
                if variant != "none":
                    cursor.execute("DROP INDEX public.tmp_gin")
            for metric, size in sizes.items():
                cursor.execute("SELECT pg_size_pretty(%s::bigint)", (size,))
                storage.append({"metric": metric, "bytes": size, "pretty": cursor.fetchone()[0]})
    return storage, timings


def benchmark(config: dict, queries: dict[str, str], runs: int, delays: list[int]) -> None:
    """Save measured query plans, timings, and explanatory statistics under results/."""
    import psycopg

    destination = ROOT / "results"
    explain = destination / "explain"
    explain.mkdir(parents=True, exist_ok=True)
    records = []
    try:
        with connect(config, "tayninh") as connection, connection.cursor() as cursor:
            versions = (
                f"Python {sys.version.split()[0]}; psycopg {psycopg.__version__}; "
                f"PostgreSQL {connection.info.server_version}; runs={runs}; autocommit; unprepared"
            )
            print(versions, file=sys.stderr)
            for delay in delays:
                set_delay(delay)
                for name, query in queries.items():
                    elapsed, rows = measure(cursor, query, runs)
                    cursor.execute("EXPLAIN (ANALYZE, VERBOSE, FORMAT JSON) " + query)
                    sites, foreign_rows = plan_metrics(cursor.fetchone()[0][0]["Plan"])
                    cursor.execute("EXPLAIN (ANALYZE, VERBOSE) " + query)
                    text = "\n".join(row[0] for row in cursor.fetchall())
                    (explain / f"{name}_delay{delay}.txt").write_text(
                        versions + "\n" + text + "\n", encoding="utf-8", newline="\n",
                    )
                    records.append({
                        "query": name, "delay_ms": delay, **timing_fields(elapsed),
                        "result_rows": len(rows), "sites_touched": sites,
                        "foreign_rows": foreign_rows,
                        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    })
    finally:
        set_delay(0)

    run_fields = [f"run{number}_ms" for number in range(1, runs + 1)]
    write_csv(destination / "results.csv", [
        "query", "delay_ms", "median_ms", *run_fields,
        "result_rows", "sites_touched", "foreign_rows", "timestamp",
    ], records)
    print(f"{'query':<6} {'delay':>6} {'median_ms':>12} {'rows':>8} {'sites':>6} {'foreign_rows':>13}")
    for record in records:
        print(f"{record['query']:<6} {record['delay_ms']:>6} {record['median_ms']:>12.3f} "
              f"{record['result_rows']:>8} {record['sites_touched']:>6} {record['foreign_rows']:>13g}")

    fragments, crossregion = inventory(config)
    write_csv(destination / "n1_fragments.csv", ["site", "table", "rows"], fragments)
    write_csv(destination / "n4_crossregion.csv", ["site", "visits", "cross_region_visits", "pct"], crossregion)
    storage, gin = storage_measurements(config, runs)
    write_csv(destination / "n5_storage.csv", ["metric", "bytes", "pretty"], storage)
    write_csv(destination / "n5_gin.csv", [
        "index", "median_ms", *run_fields, "matched_visits", "index_used",
    ], gin)
    print(f"\n{'GIN':<16} {'median_ms':>12} {'matches':>9} {'used':>6}")
    for record in gin:
        print(f"{record['index']:<16} {record['median_ms']:>12.3f} "
              f"{record['matched_visits']:>9} {str(record['index_used']):>6}")


def self_test() -> None:
    """Check site deduplication, pushed-down joins, loops, and warm-up exclusion offline."""
    from unittest.mock import Mock, patch

    local = {"Node Type": "Index Only Scan", "Schema": "public", "Relation Name": "visit", "Actual Loops": 1}
    remote = {"Node Type": "Async Foreign Scan", "Schema": "hcm", "Actual Rows": 3, "Actual Loops": 2}
    joined = {"Node Type": "Foreign Join", "Relations": '("cantho".visit INNER JOIN cantho.patient)',
              "Actual Rows": 4, "Actual Loops": 1}
    aggregate = {"Node Type": "Foreign Scan", "Relations": "Aggregate on (hcm.visit)",
                 "Actual Rows": 1, "Actual Loops": 1}
    skipped = {"Node Type": "Foreign Scan", "Schema": "dongnai", "Actual Rows": 0, "Actual Loops": 0}
    plan = {"Node Type": "Append", "Actual Loops": 1, "Plans": [local, remote, joined, aggregate, skipped]}
    assert plan_metrics(plan) == (3, 11)
    assert plan_metrics(local) == (1, 0)
    try:
        plan_metrics({**remote, "Schema": "unknown"})
    except ValueError:
        pass
    else:
        raise AssertionError("Unknown foreign sites must not be silently ignored")
    cursor = Mock()
    cursor.fetchall.return_value = [(1,)]
    with patch(__name__ + ".perf_counter", side_effect=[0, 1, 2, 2.002, 3, 3.004, 4, 4.006, 5, 5.008]):
        elapsed, rows = measure(cursor, "SELECT 1", 5)
    assert timing_fields(elapsed)["median_ms"] == 5.0
    assert timing_fields(elapsed)["run1_ms"] == 1000.0
    assert rows == [(1,)] and cursor.execute.call_count == cursor.fetchall.call_count == 5
    print("self-test: PASS")


def main() -> int:
    """Validate command-line inputs and run measurements or the offline self-check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5, help="executions including discarded warm-up (minimum 2)")
    parser.add_argument("--delays", default="0,30", help="comma-separated nonnegative integer milliseconds")
    parser.add_argument("--only", default="q1,q2,q3,q4,q5", help="comma-separated queries; N1/N4/N5 still run")
    parser.add_argument("--self-test", action="store_true", help="run offline checks; no psycopg required")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.runs < 2:
        parser.error("--runs must be at least 2")
    if not re.fullmatch(r"\s*\d+\s*(,\s*\d+\s*)*", args.delays, flags=re.ASCII):
        parser.error("--delays must contain nonnegative integers, such as 0,30")
    delays = [int(value) for value in args.delays.split(",")]
    selected = [value.strip().lower() for value in args.only.split(",")]
    if len(set(delays)) != len(delays):
        parser.error("--delays must not contain duplicates")
    if any(name not in {f"q{number}" for number in range(1, 6)} for name in selected) or len(set(selected)) != len(selected):
        parser.error("--only must contain distinct names from q1,q2,q3,q4,q5")
    try:
        import psycopg
    except ImportError as error:
        parser.exit(1, f"psycopg unavailable; use ~/cs5104-venv/bin/python: {error}\n")
    try:
        with (ROOT / "deploy.toml").open("rb") as source:
            config = tomllib.load(source)
        queries = {name: (ROOT / "sql/queries" / f"{name}.sql").read_text(encoding="utf-8") for name in selected}
        benchmark(config, queries, args.runs, delays)
    except (OSError, KeyError, ValueError, RuntimeError, psycopg.Error, subprocess.CalledProcessError) as error:
        print(f"bench: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("bench: interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
