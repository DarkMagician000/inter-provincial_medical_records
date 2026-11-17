#!/usr/bin/env python3
"""Check an idle deployment against ref; --self-test runs without databases."""

from __future__ import annotations

import ipaddress
import json
import re
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
ORIGINAL_IDS = {
    table: (keys.split(",")[0], {"patient": 20000, "prescription": 200000}.get(table, 80000))
    for table, keys in KEYS.items()
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
    actual_table: str, expected_table: str, keys: str, original_only: bool = False,
) -> tuple[bool, str]:
    """Stream two tables ordered by their trusted, fixed primary-key definitions."""
    where = ""
    if original_only:
        key, maximum = ORIGINAL_IDS[expected_table]
        where = f" WHERE {key} <= {maximum}"
    with actual.transaction(), expected.transaction():
        with actual.cursor(name="actual_rows") as actual_rows, expected.cursor(name="ref_rows") as ref_rows:
            actual_rows.itersize = ref_rows.itersize = 10000
            actual_rows.execute(f"SELECT * FROM public.{actual_table}{where} ORDER BY {keys}")
            ref_rows.execute(f"SELECT * FROM public.{expected_table}{where} ORDER BY {keys}")
            return compare_ordered(actual_rows, ref_rows)


def zero_rows(connection: psycopg.Connection, query: str, params: tuple = ()) -> tuple[bool, str]:
    """Run a violation-count query; return success only for zero violations."""
    count = connection.execute(query, params).fetchone()[0]
    return count == 0, f"violations={count}"


def check_new_ids(connection: psycopg.Connection, table: str, site_no: int) -> tuple[bool, str]:
    """Check every new ID against the storing site's range, including child rows."""
    key, maximum = ORIGINAL_IDS[table]
    start = site_no * 1000000 + 1
    end = site_no * 1000000 + 999999
    return zero_rows(connection, f"""
        SELECT count(*) FROM public.{table}
        WHERE {key} > {maximum} AND {key} NOT BETWEEN {start} AND {end}
    """)


def count_new_rows(connection: psycopg.Connection) -> int:
    """Count new physical rows in all eight fragments, as on the dashboard."""
    counts = [
        f"(SELECT count(*) FROM public.all_{table} WHERE {key} > {maximum})"
        for table, (key, maximum) in ORIGINAL_IDS.items()
    ]
    return connection.execute("SELECT " + " + ".join(counts)).fetchone()[0]


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


def check_pushdown(plan: str, view: str) -> tuple[bool, str]:
    """Require three foreign scans, each reading the expected per-site view."""
    scans = sum("foreign scan" in line.lower() for line in plan.splitlines())
    remote = [line.split("Remote SQL:", 1)[1] for line in plan.splitlines() if "Remote SQL:" in line]
    views = sum(bool(re.search(rf"\b{view}\b", query, re.IGNORECASE)) for query in remote)
    return scans == len(remote) == views == 3, f"foreign_scans={scans}, remote_sql={len(remote)}, {view}={views} (expected 3 each)"


def check_all(connections: dict[str, psycopg.Connection]) -> int:
    """Run all deployment checks; return 1 if any required check fails."""
    central, reference = connections["tayninh"], connections["ref"]
    failed = 0
    for table, keys in KEYS.items():
        failed += not run_check(f"{table}.completeness_reconstruction", lambda: compare_tables(
            central, reference, f"all_{table}", table, keys, original_only=True,
        ))
        failed += not run_check(f"{table}.disjointness", lambda: zero_rows(central, f"""
            SELECT count(*) FROM (
                SELECT {keys} FROM public.all_{table}
                GROUP BY {keys} HAVING count(*) > 1
            ) duplicates
        """))
    for site_no, site in enumerate(SITES, 1):
        connection = connections[site]
        for table in KEYS:
            failed += not run_check(f"{site}.{table}.new_id_range", lambda: check_new_ids(
                connection, table, site_no,
            ))
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
    try:
        new_rows = count_new_rows(central)
    except psycopg.Error as error:
        print(f"FAIL new_rows.count: {' '.join(str(error).splitlines())}")
        failed += 1
        new_rows = None
    for number in range(1, 6):
        if new_rows:
            print(f"Q{number}.central_equals_ref: SKIP ({new_rows} dòng mới; chạy make load để so lại)")
        elif new_rows == 0:
            failed += not run_check(f"Q{number}.central_equals_ref", lambda: query_match(central, reference, number))
    failed += not run_check("Q1.no_foreign_scan", lambda: (
        "foreign scan" not in explain(central, 1).lower(), "EXPLAIN (VERBOSE) must contain no Foreign Scan",
    ))
    for number, view in ((2, "drug_cost_by_year"), (5, "cardio_patient_bp")):
        failed += not run_check(f"Q{number}.pushdown", lambda: check_pushdown(explain(central, number), view))
    return int(failed > 0)


def self_test() -> None:
    """Exercise missing/extra rows, duplicates, composite keys and JSON comparisons."""
    import io
    import sqlite3
    from contextlib import redirect_stdout
    from unittest.mock import MagicMock, patch

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
    for view in ("drug_cost_by_year", "cardio_patient_bp"):
        branch = f"Async Foreign Scan\n  Remote SQL: SELECT * FROM public.{view}\n"
        assert check_pushdown(branch * 3, view)[0]
        assert not check_pushdown(branch * 2, view)[0]
        assert not check_pushdown(branch * 4, view)[0]
        assert not check_pushdown((branch * 3).replace(view, "visit", 1), view)[0]
        assert not check_pushdown((branch * 3).replace(view, view + "_wrong"), view)[0]
        assert not check_pushdown((branch * 3).replace("Foreign Scan", "Seq Scan", 1), view)[0]
    with sqlite3.connect(":memory:") as connection:
        connection.execute("ATTACH DATABASE ':memory:' AS public")
        for table, (key, maximum) in ORIGINAL_IDS.items():
            assert key == {"patient": "patient_id", "prescription": "prescription_id"}.get(table, "visit_id")
            assert maximum == {"patient": 20000, "prescription": 200000}.get(table, 80000)
            connection.execute(f"CREATE TABLE public.{table} ({key} INTEGER)")
            connection.execute(f"CREATE VIEW public.all_{table} AS SELECT * FROM {table}")
        for table, (key, maximum) in ORIGINAL_IDS.items():
            for site_no in range(1, 5):
                start, end = site_no * 1000000 + 1, site_no * 1000000 + 999999
                connection.executemany(f"INSERT INTO public.{table} VALUES (?)", [(maximum,), (start,), (end,)])
                assert check_new_ids(connection, table, site_no)[0]
                assert count_new_rows(connection) == 2
                for invalid in (maximum + 1, start - 1, end + 1):
                    connection.execute(f"INSERT INTO public.{table} VALUES (?)", (invalid,))
                    assert not check_new_ids(connection, table, site_no)[0]
                    connection.execute(f"DELETE FROM public.{table} WHERE {key} = ?", (invalid,))
                connection.execute(f"DELETE FROM public.{table}")
        assert count_new_rows(connection) == 0
    actual, reference = MagicMock(), MagicMock()
    for table, (key, maximum) in ORIGINAL_IDS.items():
        assert compare_tables(actual, reference, f"all_{table}", table, KEYS[table], original_only=True)[0]
        actual.cursor.return_value.__enter__.return_value.execute.assert_called_with(
            f"SELECT * FROM public.all_{table} WHERE {key} <= {maximum} ORDER BY {KEYS[table]}"
        )
        reference.cursor.return_value.__enter__.return_value.execute.assert_called_with(
            f"SELECT * FROM public.{table} WHERE {key} <= {maximum} ORDER BY {KEYS[table]}"
        )
    assert compare_tables(actual, reference, "hospital", "hospital", "hospital_id")[0]
    actual.cursor.return_value.__enter__.return_value.execute.assert_called_with(
        "SELECT * FROM public.hospital ORDER BY hospital_id"
    )
    plans = {1: "Seq Scan on visit", **{
        number: f"Async Foreign Scan\n  Remote SQL: SELECT * FROM public.{view}\n" * 3
        for number, view in ((2, "drug_cost_by_year"), (5, "cardio_patient_bp"))
    }}
    matched = MagicMock(return_value=(True, "same"))
    ranges = MagicMock(return_value=(True, "valid"))
    counter = MagicMock(return_value=0)
    with patch.multiple(sys.modules[__name__],
                        compare_tables=MagicMock(return_value=(True, "same")),
                        zero_rows=MagicMock(return_value=(True, "zero")),
                        check_new_ids=ranges, count_new_rows=counter, query_match=matched,
                        explain=lambda connection, number: plans[number]):
        connections = dict.fromkeys((*SITES, "ref"))
        for new_count in (0, 102):
            counter.return_value = new_count
            matched.reset_mock()
            ranges.reset_mock()
            output = io.StringIO()
            with redirect_stdout(output):
                assert check_all(connections) == 0
            assert matched.call_count == (0 if new_count else 5)
            assert ranges.call_count == len(SITES) * len(KEYS)
            assert output.getvalue().count("SKIP (102 dòng mới; chạy make load để so lại)") == (5 if new_count else 0)
        ranges.return_value = (False, "wrong site range")
        with redirect_stdout(io.StringIO()):
            assert check_all(connections) == 1
        ranges.return_value = (True, "valid")
        plans[2] = "Seq Scan on visit"
        with redirect_stdout(io.StringIO()):
            assert check_all(connections) == 1
    print("PASS self-test: reconstruction, multisets, JSON types, pushdown and new-ID boundaries")


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
            if name != "ref" and (type(site["site_no"]) is not int or site["site_no"] != SITES.index(name) + 1):
                raise ValueError(f"Invalid site_no for {name}")
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
