#!/usr/bin/env python3
"""Check an idle deployment against ref; --self-test runs without databases."""

from __future__ import annotations

import ipaddress
import json
import sys
import tomllib
from collections import Counter
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from decimal import Decimal
from functools import partial
from itertools import zip_longest
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None


ROOT = Path(__file__).resolve().parents[1]
SITES = ("tayninh", "hcm", "cantho", "dongnai")
KEYS = {
    "patient": "patient_id",
    "visit": "visit_id",
    "prescription": "prescription_id",
    "visit_cardio": "visit_id",
    "visit_eye": "visit_id",
    "visit_blood": "visit_id",
    "visit_eye_diagnosis": "visit_id, seq",
    "visit_blood_test": "visit_id, code",
}
FOREIGN_KEYS = (
    ("visit", "patient_id", "patient"),
    ("visit", "hospital_id", "hospital"),
    ("prescription", "visit_id", "visit"),
    ("prescription", "drug_code", "drug"),
    ("visit_cardio", "visit_id", "visit"),
    ("visit_eye", "visit_id", "visit"),
    ("visit_blood", "visit_id", "visit"),
    ("visit_eye_diagnosis", "visit_id", "visit_eye"),
    ("visit_blood_test", "visit_id", "visit_blood"),
)
ARRAY_CHECKS = {
    "eye.diagnoses_values_count": """
        SELECT count(*) FROM public.visit expected
        LEFT JOIN (
            SELECT visit_id, jsonb_agg(diagnosis ORDER BY seq) AS diagnoses,
                   min(seq) AS first_seq, max(seq) AS last_seq, count(*) AS row_count
            FROM public.visit_eye_diagnosis GROUP BY visit_id
        ) actual USING (visit_id)
        WHERE expected.specialty = 'eye' AND (
            expected.result->'diagnoses'
              IS DISTINCT FROM coalesce(actual.diagnoses, '[]'::jsonb)
            OR actual.first_seq <> 1 OR actual.last_seq <> actual.row_count
        )
    """,
    "blood.tests_values_count": """
        SELECT count(*) FROM public.visit expected
        LEFT JOIN (
            SELECT visit_id, jsonb_agg(jsonb_build_object(
                'code', code, 'value', value, 'unit', unit
            ) ORDER BY code) AS tests
            FROM public.visit_blood_test GROUP BY visit_id
        ) actual USING (visit_id)
        WHERE expected.specialty = 'blood' AND (
            jsonb_typeof(expected.result->'tests') IS DISTINCT FROM 'array'
            OR (SELECT coalesce(jsonb_agg(test ORDER BY test->>'code'), '[]'::jsonb)
                FROM jsonb_array_elements(expected.result->'tests') AS items(test))
               IS DISTINCT FROM coalesce(actual.tests, '[]'::jsonb)
        )
    """,
}


def freeze(value: object) -> object:
    """Make SQL/JSON values hashable, preserving JSON object/array/boolean types."""
    if isinstance(value, dict):
        return frozenset((key, freeze(item)) for key, item in value.items())
    if isinstance(value, list):
        return (list, tuple(freeze(item) for item in value))
    if isinstance(value, tuple):
        return tuple(freeze(item) for item in value)
    if isinstance(value, bool):
        return (bool, value)
    return value


def compare_ordered(actual: Iterable[tuple], expected: Iterable[tuple]) -> tuple[bool, str]:
    """Compare PK-ordered row streams exactly, including missing and extra rows."""
    sentinel = object()
    actual_count = expected_count = differences = 0
    for actual_row, expected_row in zip_longest(actual, expected, fillvalue=sentinel):
        actual_count += actual_row is not sentinel
        expected_count += expected_row is not sentinel
        differences += freeze(actual_row) != freeze(expected_row)
    return differences == 0, (
        f"rows={actual_count}, ref={expected_count}, differing_positions={differences}"
    )


def compare_results(actual: Iterable[tuple], expected: Iterable[tuple]) -> tuple[bool, str]:
    """Compare unordered query results as multisets, not sets."""
    actual_rows = Counter(freeze(row) for row in actual)
    expected_rows = Counter(freeze(row) for row in expected)
    missing = (expected_rows - actual_rows).total()
    extra = (actual_rows - expected_rows).total()
    return missing == extra == 0, (
        f"rows={actual_rows.total()}, ref={expected_rows.total()}, missing={missing}, extra={extra}"
    )


def compare_tables(
    actual: psycopg.Connection, expected: psycopg.Connection,
    actual_table: str, expected_table: str, keys: str,
) -> tuple[bool, str]:
    """Stream two tables ordered by their trusted, fixed primary-key definitions."""
    with actual.transaction(), expected.transaction():
        with actual.cursor(name="actual_rows") as actual_rows, expected.cursor(name="ref_rows") as ref_rows:
            actual_rows.itersize = ref_rows.itersize = 10000
            actual_rows.execute(f"SELECT * FROM public.{actual_table} ORDER BY {keys}")
            ref_rows.execute(f"SELECT * FROM public.{expected_table} ORDER BY {keys}")
            return compare_ordered(actual_rows, ref_rows)


def zero_rows(connection: psycopg.Connection, query: str, params: tuple = ()) -> tuple[bool, str]:
    """Run a violation-count query; return success only for zero violations."""
    count = connection.execute(query, params).fetchone()[0]
    return count == 0, f"violations={count}"


def scalar_query(specialty: str) -> str:
    """Build a two-way subtype/value check for a fixed specialty."""
    payload = "to_jsonb(actual) - 'visit_id'"
    if specialty == "cardio":
        payload = """jsonb_build_object(
            'bp_systolic', actual.bp_systolic, 'bp_diastolic', actual.bp_diastolic,
            'heart_rate', actual.heart_rate,
            'ecg', jsonb_build_object('rhythm', actual.ecg_rhythm, 'qt_ms', actual.ecg_qt_ms)
        )"""
    return f"""
        WITH expected AS (
            SELECT visit_id, result FROM public.visit WHERE specialty = '{specialty}'
        )
        SELECT count(*) FROM expected
        FULL JOIN public.visit_{specialty} actual USING (visit_id)
        WHERE expected.visit_id IS NULL OR actual.visit_id IS NULL
           OR NOT coalesce(expected.result @> ({payload}), false)
    """


def run_check(label: str, action: Callable[[], tuple[bool, str]]) -> bool:
    """Print exactly one PASS/FAIL line; SQL errors fail without aborting later checks."""
    try:
        passed, detail = action()
    except (psycopg.Error, OSError, ValueError, TypeError, KeyError) as error:
        passed, detail = False, f"{type(error).__name__}: {error}"
    print(f"{'PASS' if passed else 'FAIL'} {label}: {' '.join(detail.splitlines())}", flush=True)
    return passed


def query_match(central: psycopg.Connection, reference: psycopg.Connection, number: int) -> tuple[bool, str]:
    """Execute matching central/ref SQL files and compare their result multisets."""
    actual = central.execute((ROOT / f"sql/queries/q{number}.sql").read_text(encoding="utf-8")).fetchall()
    expected = reference.execute((ROOT / f"sql/queries_ref/q{number}.sql").read_text(encoding="utf-8")).fetchall()
    passed, detail = compare_results(actual, expected)
    if number == 1:
        detail += f"; visits={sum(row[1] for row in actual)}"
    elif number == 2:
        detail += "; totals=" + ", ".join(f"{province}={total}" for province, total in sorted(actual))
    return passed, detail


def explain(connection: psycopg.Connection, number: int) -> str:
    """Return the central query's verbose plan without executing the query."""
    query = (ROOT / f"sql/queries/q{number}.sql").read_text(encoding="utf-8")
    return "\n".join(row[0] for row in connection.execute("EXPLAIN (VERBOSE) " + query))


def check_all(connections: dict[str, psycopg.Connection]) -> int:
    """Run all deployment checks; return 1 if any required check fails."""
    central, reference = connections["tayninh"], connections["ref"]
    failed = 0
    for table, keys in KEYS.items():
        failed += not run_check(f"{table}.completeness_reconstruction", lambda: compare_tables(
            central, reference, f"all_{table}", table, keys,
        ))
        failed += not run_check(f"{table}.disjointness", lambda: zero_rows(central, f"""
            SELECT count(*) FROM (
                SELECT {keys} FROM public.all_{table}
                GROUP BY {keys} HAVING count(*) > 1
            ) duplicates
        """))
    for site in SITES:
        connection = connections[site]
        failed += not run_check(f"{site}.patient_region", lambda: zero_rows(connection,
            "SELECT count(*) FROM public.patient WHERE home_province IS DISTINCT FROM %s", (site,),
        ))
        for child, key, parent in FOREIGN_KEYS:
            failed += not run_check(f"{site}.fk.{child}.{key}", lambda: zero_rows(connection, f"""
                SELECT count(*) FROM public.{child} child
                WHERE NOT EXISTS (SELECT 1 FROM public.{parent} parent WHERE parent.{key} = child.{key})
            """))
        for table, keys in (("hospital", "hospital_id"), ("drug", "drug_code")):
            failed += not run_check(f"{site}.{table}.replica", lambda: compare_tables(
                connection, reference, table, table, keys,
            ))
        for specialty in ("cardio", "eye", "blood"):
            failed += not run_check(f"{site}.jsonb.{specialty}.scalars", lambda: zero_rows(
                connection, scalar_query(specialty),
            ))
        for name, query in ARRAY_CHECKS.items():
            failed += not run_check(f"{site}.jsonb.{name}", lambda: zero_rows(connection, query))
    for number in range(1, 6):
        failed += not run_check(f"Q{number}.central_equals_ref", lambda: query_match(central, reference, number))
    failed += not run_check("Q1.no_foreign_scan", lambda: (
        "foreign scan" not in explain(central, 1).lower(), "EXPLAIN (VERBOSE) must contain no Foreign Scan",
    ))
    for number in (2, 5):
        try:
            remote = [line.upper() for line in explain(central, number).splitlines() if "Remote SQL:" in line]
            print(f"INFO Q{number}.pushdown: remote_sql={len(remote)}, "
                  f"GROUP BY={sum('GROUP BY' in line for line in remote)}, "
                  f"JOIN={sum('JOIN' in line for line in remote)}")
        except (psycopg.Error, OSError) as error:
            print(f"INFO Q{number}.pushdown: unavailable: {' '.join(str(error).splitlines())}")
    return int(failed > 0)


def self_test() -> None:
    """Exercise missing/extra rows, duplicates, composite keys and JSON comparisons."""
    rows = [(1, 1, {"value": Decimal("1.0"), "items": ["a", "b"]}), (1, 2, None)]
    equivalent = [(1, 1, {"items": ["a", "b"], "value": 1}), (1, 2, None)]
    assert compare_ordered(iter(rows), iter(equivalent))[0]
    assert compare_ordered([], [])[0]
    assert not compare_ordered(rows[:-1], rows)[0]
    assert not compare_ordered(rows + [rows[-1]], rows)[0]
    assert not compare_ordered([(1, 1, None), rows[-1]], rows)[0]
    assert compare_results(rows, reversed(equivalent))[0]
    assert not compare_results(rows + [rows[0]], rows)[0]
    assert not compare_results(rows, rows + [rows[0]])[0]
    assert not compare_results([rows[0], rows[0]], rows)[0]
    assert not compare_results([(True,)], [(1,)])[0]
    assert not compare_results([({"key": 1},)], [([["key", 1]],)])[0]
    assert not compare_results([([1, 2],)], [([2, 1],)])[0]
    print("PASS self-test: ordered reconstruction, multiset results and JSON types")


def main() -> int:
    """Read deploy.toml, connect read-only to the five databases, then check them."""
    if psycopg is None:
        print("FAIL dependency: psycopg 3 is required; use ~/cs5104-venv/bin/python")
        return 1
    from psycopg.types.json import set_json_loads

    try:
        with (ROOT / "deploy.toml").open("rb") as source:
            config = tomllib.load(source)
        if config["dbname"] != "hospital" or set(config["sites"]) != set(SITES):
            raise ValueError("Expected hospital database and exactly four agreed sites")
        if config["sites"]["tayninh"].get("central") is not True:
            raise ValueError("Expected tayninh as central site")
        endpoints = {**config["sites"], "ref": config["ref"]}
        seen = set()
        for name, site in endpoints.items():
            address = ipaddress.ip_address(site["ip"])
            port = site["port"]
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError(f"Invalid port for {name}: {port!r}")
            if (address, port) in seen:
                raise ValueError(f"Duplicate database endpoint for {name}")
            seen.add((address, port))
        with ExitStack() as stack:
            connections = {}
            for name, site in endpoints.items():
                connection = stack.enter_context(psycopg.connect(
                    host=site["ip"], port=site["port"], dbname=config["dbname"], user="postgres",
                    connect_timeout=10, autocommit=True,
                    options="-c default_transaction_read_only=on -c statement_timeout=120000",
                ))
                set_json_loads(partial(json.loads, parse_float=Decimal), connection)
                connections[name] = connection
            return check_all(connections)
    except (psycopg.Error, OSError, ValueError, TypeError, KeyError) as error:
        print(f"FAIL setup: {' '.join(str(error).splitlines())}")
        return 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    elif sys.argv[1:]:
        print("FAIL arguments: usage: check.py [--self-test]")
        sys.exit(1)
    else:
        sys.exit(main())
