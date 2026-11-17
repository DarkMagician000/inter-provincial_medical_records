"""Đọc CSV lab, kiểm chứng và sinh docs/data_explorer.html offline.

Chạy: python scripts/explore_data.py [--self-test]. Chỉ dùng thư viện chuẩn.
"""

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
from html import escape
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import csv
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "CS5104_Project_DataGen/de01_hospital/output"
OUTPUT = ROOT / "docs/data_explorer.html"
SITES = ("tayninh", "hcm", "cantho", "dongnai")
SPECIALTIES = ("cardio", "eye", "blood")
UNKNOWN_UNIT = "Đề không quy định; giữ nguyên số gốc"
SCHEMA = {
    "hospital": ("Bệnh viện; nơi diễn ra lượt khám, không phải nơi cư trú của bệnh nhân.", [
        ("hospital_id", "integer", "Mã bệnh viện", "Mã"),
        ("name", "text", "Tên bệnh viện", "—"),
        ("province", "text", "Tỉnh đặt bệnh viện", "Mã tỉnh"),
    ]),
    "drug": ("Danh mục thuốc; price là đơn giá, unit là đơn vị cấp phát.", [
        ("drug_code", "text", "Mã thuốc", "Mã"),
        ("name", "text", "Tên thuốc và hàm lượng giả lập", "—"),
        ("unit", "text", "Đơn vị cấp phát", "viên / gói / ống / chai / tuýp"),
        ("price", "numeric", "Đơn giá mỗi đơn vị thuốc", "đồng / drug.unit"),
    ]),
    "patient": ("Bệnh nhân; home_province xác định trạm lưu hồ sơ trong phương án đang xem xét.", [
        ("patient_id", "integer", "Mã bệnh nhân", "Mã"),
        ("full_name", "text", "Họ tên giả lập", "—"),
        ("birth_year", "smallint", "Năm sinh", "Năm"),
        ("gender", "char", "Giới tính M/F theo bộ sinh", "Mã"),
        ("home_province", "text", "Tỉnh cư trú", "Mã tỉnh"),
    ]),
    "visit": ("Một lượt khám; result chứa kết quả JSON theo specialty, đồng thời có bản quan hệ tương đương.", [
        ("visit_id", "integer", "Mã lượt khám", "Mã"),
        ("patient_id", "integer", "Bệnh nhân được khám", "Mã patient"),
        ("hospital_id", "integer", "Bệnh viện thực hiện khám", "Mã hospital"),
        ("specialty", "text", "cardio: tim mạch; eye: mắt; blood: xét nghiệm máu", "Mã"),
        ("visit_date", "date", "Ngày khám; dùng lọc năm/tháng Q1–Q3", "YYYY-MM-DD"),
        ("result", "jsonb", "Kết quả có cấu trúc theo specialty", "Theo từng trường JSON"),
    ]),
    "prescription": ("Một dòng thuốc trong một lượt khám; không đồng nghĩa một đơn thuốc hoàn chỉnh. quantity chưa được đề nói rõ là tổng lượng hay lượng/ngày.", [
        ("prescription_id", "integer", "Mã dòng đơn thuốc", "Mã"),
        ("visit_id", "integer", "Lượt khám kê thuốc", "Mã visit"),
        ("drug_code", "text", "Thuốc được kê", "Mã drug"),
        ("quantity", "integer", "Số lượng thuốc; cần chốt có tính theo ngày không", "drug.unit; ý nghĩa theo ngày chưa chốt"),
        ("days", "smallint", "Số ngày dùng", "Ngày"),
    ]),
    "visit_cardio": ("Bản quan hệ của result khi specialty = cardio; ecg được làm phẳng thành hai cột.", [
        ("visit_id", "integer", "Lượt khám tim mạch", "Mã visit"),
        ("bp_systolic", "smallint", "Huyết áp tâm thu", "mmHg"),
        ("bp_diastolic", "smallint", "Huyết áp tâm trương", "mmHg"),
        ("heart_rate", "smallint", "Nhịp tim", "Lần/phút"),
        ("ecg_rhythm", "text", "Nhịp điện tim; result.ecg.rhythm", "Mã"),
        ("ecg_qt_ms", "smallint", "Khoảng QT; result.ecg.qt_ms", "ms"),
    ]),
    "visit_eye": ("Bản quan hệ của result khi specialty = eye; mảng diagnoses nằm ở visit_eye_diagnosis.", [
        ("visit_id", "integer", "Lượt khám mắt", "Mã visit"),
        ("va_left", "numeric", "Thị lực mắt trái", UNKNOWN_UNIT),
        ("va_right", "numeric", "Thị lực mắt phải", UNKNOWN_UNIT),
        ("iop_mmhg", "smallint", "Nhãn áp", "mmHg"),
    ]),
    "visit_eye_diagnosis": ("Mỗi phần tử result.diagnoses là một dòng; seq bảo toàn thứ tự mảng, bắt đầu từ 1.", [
        ("visit_id", "integer", "Lượt khám mắt cha", "Mã visit_eye"),
        ("seq", "smallint", "Thứ tự chẩn đoán trong mảng", "Vị trí từ 1"),
        ("diagnosis", "text", "Mã chẩn đoán mắt", "Mã"),
    ]),
    "visit_blood": ("Bản quan hệ của result khi specialty = blood; các xét nghiệm bổ sung ở visit_blood_test.", [
        ("visit_id", "integer", "Lượt xét nghiệm máu", "Mã visit"),
        ("wbc", "numeric", "Bạch cầu", UNKNOWN_UNIT),
        ("rbc", "numeric", "Hồng cầu", UNKNOWN_UNIT),
        ("glucose", "numeric", "Đường huyết", UNKNOWN_UNIT),
    ]),
    "visit_blood_test": ("Mỗi phần tử result.tests là một dòng, nhận diện bằng (visit_id, code); lược đồ không giữ thứ tự mảng tests.", [
        ("visit_id", "integer", "Lượt xét nghiệm máu cha", "Mã visit_blood"),
        ("code", "text", "Mã xét nghiệm bổ sung", "ALT / AST / HbA1c / CHOL / TG / CREA"),
        ("value", "numeric", "Giá trị xét nghiệm, không đổi đơn vị", "Theo cột unit cùng dòng"),
        ("unit", "text", "Đơn vị gốc của xét nghiệm", "U/L / % / mmol/L / umol/L"),
    ]),
}
PRIMARY_KEYS = {table: (columns[0][0],) for table, (_, columns) in SCHEMA.items()}
PRIMARY_KEYS.update(visit_eye_diagnosis=("visit_id", "seq"), visit_blood_test=("visit_id", "code"))
FOREIGN_KEYS = {
    "visit": [("patient_id", "patient"), ("hospital_id", "hospital")],
    "prescription": [("visit_id", "visit"), ("drug_code", "drug")],
    "visit_cardio": [("visit_id", "visit")],
    "visit_eye": [("visit_id", "visit")],
    "visit_eye_diagnosis": [("visit_id", "visit_eye")],
    "visit_blood": [("visit_id", "visit")],
    "visit_blood_test": [("visit_id", "visit_blood")],
}
RELATIONAL = tuple(table for table in SCHEMA if table.startswith("visit_"))


def json_text(value: object, pretty: bool = False) -> str:
    """Mã hoá JSON; Decimal giữ chính xác dưới dạng chuỗi cho dữ liệu kiểm toán."""
    return json.dumps(value, ensure_ascii=False, default=str, allow_nan=False,
                      indent=2 if pretty else None, sort_keys=True)


def reject_constant(value: str) -> None:
    """Từ chối NaN/Infinity không hợp lệ trong JSON."""
    raise ValueError(f"Hằng JSON không hợp lệ: {value}")


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    """Đọc object JSON, từ chối khoá trùng thay vì âm thầm ghi đè."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Khoá JSON trùng: {key}")
        result[key] = value
    return result


def parse_value(value: object, sql_type: str) -> object:
    """Chuyển giá trị CSV/JSON sang kiểu Python tương ứng, không đổi đơn vị."""
    if value is None or value == "":
        return None
    if sql_type in ("integer", "smallint"):
        parsed = int(str(value))
        limit = 2 ** (15 if sql_type == "smallint" else 31)
        if not -limit <= parsed < limit:
            raise ValueError(f"Ngoài miền {sql_type}: {value}")
        return parsed
    if sql_type == "numeric":
        parsed = Decimal(str(value))
        if not parsed.is_finite():
            raise ValueError(f"Số không hữu hạn: {value}")
        return parsed
    if sql_type == "date":
        parsed = date.fromisoformat(str(value))
        if parsed.isoformat() != value:
            raise ValueError(f"Ngày không đúng YYYY-MM-DD: {value}")
        return value
    if sql_type == "jsonb":
        parsed = json.loads(str(value), parse_constant=reject_constant, object_pairs_hook=unique_object)
        if not isinstance(parsed, dict):
            raise ValueError("visit.result phải là object JSON")
        return parsed
    if not isinstance(value, str) or (sql_type == "char" and len(value) != 1):
        raise ValueError(f"Giá trị không đúng kiểu {sql_type}: {value!r}")
    return value


def load_dataset(folder: Path) -> tuple[dict, dict]:
    """Đọc đủ 10 CSV và summary, báo chính xác vị trí dữ liệu lỗi."""
    tables = {}
    for table, (_, columns) in SCHEMA.items():
        path = folder / f"{table}.csv"
        rows = []
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source, strict=True)
            if next(reader, None) != [column[0] for column in columns]:
                raise ValueError(f"{path}: header không đúng lược đồ đề")
            for record, values in enumerate(reader, 2):
                if len(values) != len(columns):
                    raise ValueError(f"{path}: bản ghi {record}: sai số cột")
                row = {}
                for (name, sql_type, _, _), value in zip(columns, values):
                    try:
                        row[name] = parse_value(value, sql_type)
                    except (ValueError, TypeError, InvalidOperation) as error:
                        raise ValueError(f"{path}: bản ghi {record}, cột {name}: {error}") from error
                rows.append(row)
        if not rows:
            raise ValueError(f"{path}: bảng rỗng, không đúng bộ lab")
        tables[table] = rows
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"),
                         parse_constant=reject_constant, object_pairs_hook=unique_object)
    if not isinstance(summary, dict) or summary.get("size") != folder.name:
        raise ValueError(f"{folder}/summary.json: size không khớp thư mục")
    return tables, summary


def validate_relations(tables: dict) -> dict:
    """Kiểm tra PK/FK, miền vùng và các cột bắt buộc để tính; trả index PK."""
    indexes = {}
    for table, rows in tables.items():
        index = {}
        for position, row in enumerate(rows, 2):
            key = tuple(row[column] for column in PRIMARY_KEYS[table])
            if None in key or key in index:
                raise ValueError(f"{table}, bản ghi {position}: PK NULL/trùng {key}")
            index[key] = row
        indexes[table] = index
    for table, references in FOREIGN_KEYS.items():
        for position, row in enumerate(tables[table], 2):
            for column, parent in references:
                if (row[column],) not in indexes[parent]:
                    raise ValueError(f"{table}, bản ghi {position}: FK {column}={row[column]} không có ở {parent}")
    for table, column, choices in [("patient", "home_province", SITES),
                                   ("hospital", "province", SITES),
                                   ("visit", "specialty", SPECIALTIES)]:
        for row in tables[table]:
            if row[column] not in choices:
                raise ValueError(f"{table}.{column} ngoài miền: {row[column]!r}")
    for table, columns in {"visit": ("visit_date", "result"), "drug": ("price",),
                           "prescription": ("quantity", "days")}.items():
        for position, row in enumerate(tables[table], 2):
            for column in columns:
                if row[column] is None:
                    raise ValueError(f"{table}, bản ghi {position}: {column} NULL; không bỏ dòng khi tính")
    return indexes


def project_result(visit: dict) -> dict:
    """Chiếu một result ra các dòng quan hệ, kiểm tra đủ khoá và kiểu JSON."""
    result = visit["result"]
    specialty = visit["specialty"]
    table = f"visit_{specialty}"
    columns = SCHEMA[table][1]
    fields = {column[0] for column in columns[1:]}
    expected = (fields - {"ecg_rhythm", "ecg_qt_ms"} | {"ecg"} if specialty == "cardio"
                else fields | {"diagnoses" if specialty == "eye" else "tests"})
    if set(result) != expected:
        raise ValueError(f"Khoá result sai: {sorted(result)}; cần {sorted(expected)}")
    values = {"visit_id": visit["visit_id"], **result}
    if specialty == "cardio":
        if not isinstance(result["ecg"], dict) or set(result["ecg"]) != {"rhythm", "qt_ms"}:
            raise ValueError("ecg phải có đúng rhythm, qt_ms")
        values.update(ecg_rhythm=result["ecg"]["rhythm"], ecg_qt_ms=result["ecg"]["qt_ms"])
    projected = {table: [{name: parse_json_value(values[name], sql_type)
                          for name, sql_type, _, _ in columns}]}
    if specialty == "eye":
        if not isinstance(result["diagnoses"], list):
            raise ValueError("diagnoses phải là mảng")
        projected["visit_eye_diagnosis"] = [
            {"visit_id": visit["visit_id"], "seq": seq, "diagnosis": parse_json_value(diagnosis, "text")}
            for seq, diagnosis in enumerate(result["diagnoses"], 1)]
    elif specialty == "blood":
        if not isinstance(result["tests"], list):
            raise ValueError("tests phải là mảng")
        tests = []
        codes = set()
        for test in result["tests"]:
            if not isinstance(test, dict) or set(test) != {"code", "value", "unit"}:
                raise ValueError("Phần tử tests phải có đúng code, value, unit")
            test = {name: parse_json_value(test[name], sql_type)
                    for name, sql_type, _, _ in SCHEMA["visit_blood_test"][1][1:]}
            if test["code"] is None or test["code"] in codes:
                raise ValueError("tests.code NULL/trùng, không ánh xạ được PK")
            codes.add(test["code"])
            tests.append({"visit_id": visit["visit_id"], **test})
        projected["visit_blood_test"] = tests
    return projected


def parse_json_value(value: object, sql_type: str) -> object:
    """Kiểm tra kiểu số JSON thật, không đồng nhất chuỗi số hoặc boolean với số."""
    if value is not None and sql_type in ("integer", "smallint", "numeric"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"JSON cần số {sql_type}, nhận {value!r}")
    if value == "" and sql_type == "text":
        return ""
    return parse_value(value, sql_type)


def reconcile_json(tables: dict) -> dict:
    """So toàn bộ trường và PK hai chiều; đếm thiếu/thừa/sai từng bảng con."""
    expected = {table: {} for table in RELATIONAL}
    invalid = []
    bad_visits = set()
    for visit in tables["visit"]:
        try:
            projected = project_result(visit)
        except (ValueError, TypeError, KeyError, InvalidOperation) as error:
            invalid.append({"visit_id": visit["visit_id"], "error": str(error)})
            bad_visits.add(visit["visit_id"])
            continue
        for table, rows in projected.items():
            for row in rows:
                expected[table][tuple(row[column] for column in PRIMARY_KEYS[table])] = row
    checks = {}
    for table in RELATIONAL:
        actual = {tuple(row[column] for column in PRIMARY_KEYS[table]): row for row in tables[table]}
        missing = expected[table].keys() - actual.keys()
        extra = actual.keys() - expected[table].keys()
        changed = {key for key in actual.keys() & expected[table].keys()
                   if actual[key] != expected[table][key]}
        bad_keys = missing | extra | changed
        bad_visits.update(key[0] for key in bad_keys)
        checks[table] = {"expected": len(expected[table]), "actual": len(actual),
                         "missing": len(missing), "extra": len(extra), "changed": len(changed),
                         "mismatch_rows": len(bad_keys), "example_keys": sorted(bad_keys)[:5]}
    return {"tables": checks, "invalid_json_count": len(invalid), "invalid_json_examples": invalid[:5],
            "mismatch_rows": sum(check["mismatch_rows"] for check in checks.values()),
            "mismatch_visits": len(bad_visits), "visits_checked": len(tables["visit"])}


def relationship_stats(tables: dict) -> list[dict]:
    """Đếm bội số hai chiều trên các bảng đã kiểm tra PK/FK, kể cả cha có 0 con."""
    def span(table: str, counts: Counter) -> tuple[int, int]:
        values = [counts[row[PRIMARY_KEYS[table][0]]] for row in tables[table]]
        return min(values, default=0), max(values, default=0)

    relations = []
    for child, references in FOREIGN_KEYS.items():
        for column, parent in references:
            counts = Counter(row[column] for row in tables[child])
            parent_counts = Counter(row[PRIMARY_KEYS[parent][0]] for row in tables[parent])
            reverse = [parent_counts[row[column]] for row in tables[child]]
            singular = PRIMARY_KEYS[child] == (column,)
            required = child in ("visit_eye_diagnosis", "visit_blood_test")
            zeros = sum(counts[row[PRIMARY_KEYS[parent][0]]] == 0 for row in tables[parent])
            note = f"{zeros} {parent} không có {child}."
            if singular:
                specialty = child.removeprefix("visit_")
                eligible = [counts[row["visit_id"]] for row in tables["visit"] if row["specialty"] == specialty]
                note += (f" PK = FK = visit_id; chỉ khi specialty = {specialty};"
                         f" trong chuyên khoa: {min(eligible, default=0)}..{max(eligible, default=0)}.")
            elif required:
                note += " 1..* theo đề; riêng FK không bảo đảm cha có ít nhất một con."
            relations.append({"parent": parent, "child": child, "fk": f"{child}.{column}",
                              "kind": "1-1" if singular else "1-n", "ends": ("1", "0..1" if singular else "1..*" if required else "0..*"),
                              "range": span(parent, counts), "reverse_range": (min(reverse, default=0), max(reverse, default=0)),
                              "zeros": zeros, "note": note})
    return relations


def analyze(tables: dict, summary: dict) -> dict:
    """Tính Q1–Q5, phân bố và cấp phát từ CSV; đối chiếu độc lập với summary."""
    indexes = validate_relations(tables)
    patients = {key[0]: row for key, row in indexes["patient"].items()}
    hospitals = {key[0]: row for key, row in indexes["hospital"].items()}
    visits = {key[0]: row for key, row in indexes["visit"].items()}
    drugs = {key[0]: row for key, row in indexes["drug"].items()}
    home_by_visit = {key: patients[row["patient_id"]]["home_province"] for key, row in visits.items()}
    regions = {
        "patient.home_province": Counter(row["home_province"] for row in patients.values()),
        "hospital.province": Counter(row["province"] for row in hospitals.values()),
        "visit.patient.home_province": Counter(home_by_visit.values()),
        "visit.hospital.province": Counter(hospitals[row["hospital_id"]]["province"] for row in visits.values()),
        "prescription.patient.home_province": Counter(home_by_visit[row["visit_id"]] for row in tables["prescription"]),
    }
    matrix = {site: dict.fromkeys(SITES, 0) for site in SITES}
    specialties = {site: dict.fromkeys(SPECIALTIES, 0) for site in SITES}
    months = defaultdict(lambda: dict.fromkeys(SITES, 0))
    q1 = dict.fromkeys(SPECIALTIES, 0)
    q3 = dict.fromkeys(SITES, 0)
    cross_patients = set()
    q4 = set()
    for visit in visits.values():
        home = home_by_visit[visit["visit_id"]]
        hospital_province = hospitals[visit["hospital_id"]]["province"]
        matrix[home][hospital_province] += 1
        specialties[home][visit["specialty"]] += 1
        months[visit["visit_date"][:7]][home] += 1
        if home != hospital_province:
            cross_patients.add(visit["patient_id"])
        if visit["visit_date"][:7] == "2026-03":
            if home == "tayninh":
                q1[visit["specialty"]] += 1
            if hospital_province == "tayninh":
                q3[home] += 1
        if visit["specialty"] == "cardio":
            pressure = visit["result"].get("bp_systolic")
            if isinstance(pressure, (int, float)) and not isinstance(pressure, bool) and pressure >= 140:
                q4.add(visit["patient_id"])
    q5 = {visits[row["visit_id"]]["patient_id"] for row in tables["visit_cardio"]
          if row["bp_systolic"] is not None and row["bp_systolic"] >= 140}
    q2 = {site: {"A": Decimal(0), "B": Decimal(0)} for site in SITES}
    prescriptions_by_visit = Counter()
    repeated_drugs = Counter()
    for prescription in tables["prescription"]:
        visit_id = prescription["visit_id"]
        prescriptions_by_visit[visit_id] += 1
        repeated_drugs[(visit_id, prescription["drug_code"])] += 1
        if visits[visit_id]["visit_date"][:4] == "2025":
            money = prescription["quantity"] * drugs[prescription["drug_code"]]["price"]
            home = home_by_visit[visit_id]
            q2[home]["A"] += money
            q2[home]["B"] += money * prescription["days"]
    per_site = {site: {} for site in SITES}
    for table, rows in tables.items():
        if table in ("hospital", "drug"):
            counts = dict.fromkeys(SITES, len(rows))
        elif table == "patient":
            counts = regions["patient.home_province"]
        else:
            counts = Counter(home_by_visit[row["visit_id"]] for row in rows)
        for site in SITES:
            per_site[site][table] = counts.get(site, 0)
    totals = {site: sum(counts.values()) for site, counts in per_site.items()}
    plans = []
    for number, machine_a in enumerate((("tayninh",), ("tayninh", "cantho"), ("tayninh", "dongnai")), 1):
        machine_b = tuple(site for site in SITES if site not in machine_a)
        plans.append({"option": number, "A_sites": machine_a, "B_sites": machine_b,
                      "A_rows": sum(totals[site] for site in machine_a),
                      "B_rows": sum(totals[site] for site in machine_b)})
    cross = sum(matrix[home][hospital] for home in SITES for hospital in SITES if home != hospital)
    json_check = reconcile_json(tables)
    counts = {table: len(rows) for table, rows in tables.items()}
    specialty_counts = dict(Counter(row["specialty"] for row in visits.values()))
    checks = []

    def check(label: str, actual: object, expected: object) -> None:
        checks.append({"label": label, "actual": actual, "expected": expected, "ok": actual == expected})

    for field, expected in (("de", 1), ("seed", 731905), ("sites", list(SITES))):
        check(f"summary.{field}", summary.get(field), expected)
    check("summary.rows", counts, summary.get("rows"))
    for field in ("patient.home_province", "hospital.province"):
        check(f"summary.by_region.{field}", dict(regions[field]), summary.get("by_region", {}).get(field))
    check("summary.cross_site.rows", cross, summary.get("cross_site", {}).get("rows"))
    check("summary.cross_site.rate", round(cross / len(visits), 4), summary.get("cross_site", {}).get("rate"))
    check("summary.jsonb_types", specialty_counts, summary.get("jsonb_types", {}).get("visit.specialty"))
    check("JSON: dòng quan hệ lệch", json_check["mismatch_rows"], 0)
    check("JSON: cấu trúc không hợp lệ", json_check["invalid_json_count"], 0)
    check("Q4/Q5: hiệu đối xứng tập patient_id", len(q4 ^ q5), 0)
    check("Bảo toàn dòng sau sao chép", sum(totals.values()), sum(counts.values()) + 3 * (counts["hospital"] + counts["drug"]))
    for table in SCHEMA:
        check(f"Phân mảnh/sao chép {table}", sum(per_site[site][table] for site in SITES),
              counts[table] * (4 if table in ("hospital", "drug") else 1))
    if summary.get("size") == "lab":
        for label, actual, expected in [("Mốc lab: patient tayninh", regions["patient.home_province"]["tayninh"], 6819),
                                        ("Mốc lab: cross_site", cross, 5724),
                                        ("Mốc task: Q1 (không có trong summary)", sum(q1.values()), 1464),
                                        ("Mốc task: Q3 (không có trong summary)", sum(q3.values()), 1436)]:
            check(label, actual, expected)
    return {"rows": counts, "regions": {label: {site: values.get(site, 0) for site in SITES} for label, values in regions.items()},
            "matrix": matrix, "specialties": specialties, "months": dict(sorted(months.items())),
            "cross_site": cross, "cross_rate": cross / len(visits), "cross_patients": len(cross_patients),
            "queries": {"Q1": q1, "Q1_total": sum(q1.values()), "Q2": q2, "Q3": q3, "Q3_total": sum(q3.values()),
                        "Q4": len(q4), "Q5": len(q5), "Q4_Q5_equal": q4 == q5, "Q4_only": sorted(q4 - q5), "Q5_only": sorted(q5 - q4)},
            "json_check": json_check, "site_rows": per_site, "site_totals": totals, "machine_plans": plans,
            "max_ids": {table: max(row[PRIMARY_KEYS[table][0]] for row in tables[table])
                        for table in ("patient", "visit", "prescription")},
            "anomalies": {"visits_without_prescription": len(visits.keys() - prescriptions_by_visit.keys()),
                          "patients_without_visit": len(patients.keys() - {row["patient_id"] for row in visits.values()}),
                          "repeated_visit_drug_pairs": sum(count > 1 for count in repeated_drugs.values()),
                          "extra_repeated_drug_rows": sum(count - 1 for count in repeated_drugs.values() if count > 1),
                          "null_cells": sum(value is None for rows in tables.values() for row in rows for value in row.values())},
            "relationships": relationship_stats(tables), "checks": checks}


def display(value: object) -> str:
    """Hiển thị số kiểu Việt Nam; dữ liệu mẫu vẫn giữ nguyên giá trị gốc."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "Có" if value else "Không"
    if isinstance(value, (dict, list, tuple)):
        return json_text(value)
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".")
    if isinstance(value, Decimal):
        return format(value, ",f").replace(",", "_").replace(".", ",").replace("_", ".")
    return str(value)


def html_table(headers: list[str] | tuple, rows: object, caption: str, raw: bool = False) -> str:
    """Sinh bảng HTML escape toàn bộ ô; raw giữ nguyên cách viết số CSV."""
    def cell(value: object) -> str:
        text = json_text(value) if isinstance(value, (dict, list, tuple)) else (str(value) if raw and value is not None else display(value))
        return escape(text)

    headings = "".join(f'<th scope="col">{escape(header)}</th>' for header in headers)
    body = "".join("<tr>" + "".join(
        f'<td class="number">{cell(value)}</td>' if isinstance(value, (int, Decimal)) and not isinstance(value, bool)
        else f"<td>{cell(value)}</td>" for value in row) + "</tr>" for row in rows)
    return f'<div class="table-scroll" tabindex="0" role="region" aria-label="{escape(caption)}"><table><caption>{escape(caption)}</caption><thead><tr>{headings}</tr></thead><tbody>{body}</tbody></table></div>'


def regional_table(values: dict, caption: str) -> str:
    """Hiển thị các hàng phân bố cùng cột tổng, theo thứ tự bốn trạm."""
    return html_table(["Chỉ tiêu", *SITES, "Tổng"],
                      [(name, *(counts[site] for site in SITES), sum(counts.values())) for name, counts in values.items()], caption)


def table_panel(table: str, lab: dict, relations: list[dict]) -> str:
    """Sinh mô tả, từ điển cột, quan hệ và 10 dòng lab cho một tab bảng."""
    description, columns = SCHEMA[table]
    dictionaries = []
    for name, sql_type, meaning, unit in columns:
        role = ["PK"] if name in PRIMARY_KEYS[table] else []
        role.extend(f"FK: {parent}.{PRIMARY_KEYS[parent][0]}" for column, parent in FOREIGN_KEYS.get(table, []) if column == name)
        dictionaries.append((name, sql_type, meaning, unit, "; ".join(role) or "—"))
    related = []
    for relation in relations:
        if table not in (relation["parent"], relation["child"]):
            continue
        role = "Cha" if table == relation["parent"] else "Con"
        related.append((role, relation["parent"], relation["child"], relation["fk"], relation["kind"], " — ".join(relation["ends"])))
    parts = [f'<section id="panel-{table}" class="table-panel" aria-labelledby="tab-{table}">',
             f'<h3>{table}</h3><p>{escape(description)}</p>',
             html_table(["Cột", "Kiểu SQL theo đề", "Ý nghĩa", "Đơn vị", "Khoá"], dictionaries, f"Từ điển cột {table}"),
             html_table(["Vai trò của bảng", "Cha", "Con", "Cột FK", "Loại", "Bội số (cha — con)"],
                        related, f"Quan hệ của {table} — khớp sơ đồ quan hệ"),
             html_table([column[0] for column in columns],
                        [[row[column[0]] for column in columns] for row in lab[table][:10]],
                        f"{table}: 10 dòng mẫu lab đầu tiên theo thứ tự CSV", raw=True)]
    return "".join(parts) + "</section>"


def relationship_diagram(relations: list[dict]) -> str:
    """Sinh SVG 10 class và 9 liên kết FK; đường trực giao, số đo lấy từ CSV."""
    boxes = {
        "hospital": (520, 130, "Bệnh viện"), "patient": (1130, 130, "Bệnh nhân"),
        "drug": (40, 450, "Thuốc"), "visit": (740, 450, "Lượt khám"),
        "prescription": (40, 900, "Dòng đơn thuốc"),
        "visit_cardio": (510, 850, "Khám tim mạch"), "visit_eye": (890, 850, "Khám mắt"),
        "visit_blood": (1270, 850, "Xét nghiệm máu"),
        "visit_eye_diagnosis": (890, 1160, "Chẩn đoán mắt"),
        "visit_blood_test": (1270, 1160, "Xét nghiệm bổ sung"),
    }
    routes = {
        ("hospital", "visit"): ([(690, 282), (690, 400), (820, 400), (820, 450)],
                                (704, 308, "start"), (834, 438, "start"), (675, 355, "end")),
        ("patient", "visit"): ([(1300, 334), (1300, 400), (1000, 400), (1000, 450)],
                               (1314, 360, "start"), (1014, 438, "start"), (1150, 385, "middle")),
        ("visit", "prescription"): ([(740, 600), (440, 600), (440, 820), (210, 820), (210, 900)],
                                      (722, 588, "end"), (224, 888, "start"), (424, 750, "end")),
        ("drug", "prescription"): ([(160, 628), (160, 900)],
                                     (174, 654, "start"), (146, 888, "end"), (174, 715, "start")),
        ("visit", "visit_cardio"): ([(850, 680), (850, 740), (680, 740), (680, 850)],
                                     (864, 706, "start"), (694, 838, "start"), (665, 790, "end")),
        ("visit", "visit_eye"): ([(960, 680), (960, 850)],
                                  (974, 706, "start"), (974, 838, "start"), (974, 765, "start")),
        ("visit", "visit_blood"): ([(1080, 620), (1440, 620), (1440, 850)],
                                    (1094, 608, "start"), (1454, 838, "start"), (1454, 730, "start")),
        ("visit_eye", "visit_eye_diagnosis"): ([(1060, 1028), (1060, 1160)],
                                                (1074, 1054, "start"), (1074, 1148, "start"), (1074, 1100, "start")),
        ("visit_blood", "visit_blood_test"): ([(1440, 1028), (1440, 1160)],
                                              (1454, 1054, "start"), (1454, 1148, "start"), (1454, 1100, "start")),
    }

    def text(position: tuple, value: str, css: str = "") -> str:
        horizontal, vertical, anchor = position
        return (f'<text x="{horizontal}" y="{vertical}" text-anchor="{anchor}" class="{css}">'
                f'{escape(value)}</text>')

    parts = ['<svg xmlns="http://www.w3.org/2000/svg" class="class-diagram" viewBox="0 0 1680 1380" '
             'role="img" aria-labelledby="diagram-title diagram-description">',
             '<title id="diagram-title">Sơ đồ quan hệ: 10 bảng, 9 liên kết FK trực tiếp</title>',
             '<desc id="diagram-description">PK: khoá chính; FK: khoá ngoại. Bội số UML ở hai đầu cạnh; '
             'số thực đo toàn bộ lab trên cạnh. Chi tiết và số đo hai chiều nằm trong bảng ngay dưới hình.</desc>',
             '<g class="json-group"><rect x="480" y="780" width="1160" height="580" rx="12"/>',
             text((510, 1135, "start"), "bản quan hệ tương đương của visit.result"), '</g>']
    kinds = {"1-n": "one-many", "1-1": "one-one"}
    for relation in relations:
        parent, child = relation["parent"], relation["child"]
        points, start, end, measure = routes[parent, child]
        low, high = relation["range"]
        reverse_low, reverse_high = relation["reverse_range"]
        parts.append(f'<g class="relationship {kinds[relation["kind"]]}" data-parent="{parent}" data-child="{child}" '
                     f'data-kind="{relation["kind"]}"><title>{escape(parent)} — {escape(child)}: '
                     f'{low}..{high} con/cha; {reverse_low}..{reverse_high} cha/con. {escape(relation["note"])}</title>')
        parts.append('<polyline class="edge" points="' + ' '.join(f'{horizontal},{vertical}' for horizontal, vertical in points) + '"/>')
        parts.extend([text(start, relation["ends"][0], "multiplicity"), text(end, relation["ends"][1], "multiplicity")])
        unit = "cha" if child in ("visit_eye_diagnosis", "visit_blood_test") else parent
        parts.append(text(measure, f"{low}..{high} / {unit}", "measurement"))
        parts.append('</g>')
    for table, (horizontal, vertical, vietnamese) in boxes.items():
        columns = SCHEMA[table][1]
        parts.append(f'<g class="diagram-class" data-table="{table}"><rect class="class-box" x="{horizontal}" '
                     f'y="{vertical}" width="340" height="{74 + 26 * len(columns)}" rx="8"/>')
        parts.extend([text((horizontal + 14, vertical + 27, "start"), table, "class-name"),
                      text((horizontal + 14, vertical + 50, "start"), vietnamese, "class-translation"),
                      f'<path class="class-divider" d="M {horizontal} {vertical + 64} H {horizontal + 340}"/>'])
        for index, (column, sql_type, _, _) in enumerate(columns):
            baseline = vertical + 88 + index * 26
            roles = (["PK"] if column in PRIMARY_KEYS[table] else [])
            if any(column == foreign for foreign, parent in FOREIGN_KEYS.get(table, [])):
                roles.append("FK")
            if sql_type == "jsonb":
                parts.append(f'<rect class="json-column" x="{horizontal + 2}" y="{baseline - 19}" width="336" height="25"/>')
            parts.extend([text((horizontal + 12, baseline, "start"), " ".join(roles), "column-key"),
                          text((horizontal + 76, baseline, "start"), column, "column-label"),
                          text((horizontal + 326, baseline, "end"), sql_type, "column-type")])
        parts.append('</g>')
    return ''.join(parts) + '</svg>'


def relationship_section(relations: list[dict]) -> str:
    """Ghép sơ đồ SVG, chú giải và bảng số đo hai chiều thành mục đầu trang."""
    rows = []
    for relation in relations:
        low, high = relation["range"]
        reverse_low, reverse_high = relation["reverse_range"]
        rows.append((relation["parent"], relation["child"], relation["fk"], relation["kind"],
                     ' — '.join(relation["ends"]), f"{low}..{high} con/cha; {reverse_low}..{reverse_high} cha/con",
                     relation["note"]))
    return ('<section id="relationships" class="relationship-section"><h2>Sơ đồ quan hệ</h2>'
            '<p>10 bảng · 9 liên kết FK trực tiếp. '
            'Bội số theo đề khác với min..max quan sát được: mọi số đo tính từ toàn bộ CSV lab, kể cả cha không có con.</p>'
            '<div class="diagram-legend" aria-label="Chú giải quan hệ">'
            '<span class="one-many"><i aria-hidden="true"></i>1-n · nét liền</span>'
            '<span class="one-one"><i aria-hidden="true"></i>1-1 · nét gạch</span></div>'
            '<p><strong>UML:</strong> 1 = đúng một; 0..1 = không hoặc một; 0..* = không hoặc nhiều; '
            '1..* = ít nhất một. <strong>Khoá:</strong> PK = khoá chính; FK = khoá ngoại; '
            'PK FK = đồng thời cả hai. Hàng result tô nổi có kiểu jsonb.</p>'
            '<p id="diagram-scroll-help" class="muted">Màn hình hẹp: cuộn ngang trong khung; dùng phím mũi tên khi khung có focus. '
            'Bảng dưới hình có đủ thông tin dạng văn bản. Số trên cạnh là số con/cha.</p>'
            '<div class="diagram-scroll" tabindex="0" role="region" aria-label="Sơ đồ 10 bảng, cuộn ngang" '
            'aria-describedby="diagram-scroll-help">' + relationship_diagram(relations) + '</div>'
            + html_table(["Cha", "Con", "Cột FK", "Loại", "Bội số theo đề (cha — con)",
                          "Min..max thực đo lab", "Ghi chú"], rows, "9 liên kết FK: bội số UML và số đo CSV lab")
            + '<p>Min..max mô tả bộ lab hiện tại, không thay thế ràng buộc lược đồ.</p></section>')


CSS = """
:root { color-scheme: light; font: 16px/1.6 system-ui, 'Segoe UI', sans-serif; color: #172c40; background: #f1f5f9; }
* { box-sizing: border-box; }
body { margin: 0; }
main { max-width: 1480px; margin: auto; padding: 24px; }
header { border-top: 6px solid #14786e; background: #fff; padding: 28px; border-radius: 12px; }
h1 { font-size: clamp(1.7rem, 4vw, 2.6rem); margin: 8px 0; line-height: 1.2; }
h2 { margin-top: 0; font-size: 1.5rem; }
h3 { margin-bottom: 8px; }
p { margin: 10px 0; }
a { color: #0757a2; text-underline-offset: 3px; }
nav { display: flex; flex-wrap: wrap; gap: 10px 22px; padding: 16px 0; }
main > section { background: white; border: 1px solid #d8e2ed; padding: 24px; border-radius: 12px; margin: 20px 0; scroll-margin-top: 16px; }
.eyebrow { font-weight: 700; color: #356276; letter-spacing: .06em; }
.muted { color: #4b6074; }
.metrics { display: grid; grid-template-columns: repeat(auto-fit,minmax(180px,1fr)); gap: 12px; margin: 20px 0; }
.metric { background: #edf7f5; border: 1px solid #b6d9d3; padding: 16px; border-radius: 8px; }
.metric strong { display: block; font-size: 1.8rem; color: #075c52; }
.notice { border-left: 5px solid #a86905; background: #fff8e6; padding: 12px 16px; margin: 16px 0; }
.pass { color: #0d6040; font-weight: 700; }
.fail { color: #a51b25; font-weight: 700; }
.table-scroll { overflow-x: auto; margin: 16px 0; border: 1px solid #cdd9e5; border-radius: 6px; }
table { width: 100%; border-collapse: collapse; font-size: .9rem; }
caption { text-align: left; padding: 10px 12px; font-weight: 700; background: #edf3f8; }
th, td { text-align: left; padding: 9px 12px; vertical-align: top; border-bottom: 1px solid #e1e8ef; overflow-wrap: anywhere; max-width: 520px; }
th { background: #e5edf5; color: #253f55; white-space: nowrap; }
.number { white-space: nowrap; font-variant-numeric: tabular-nums; }
tbody tr:nth-child(even) { background: #f8fafc; }
tbody tr:hover { background: #edf7f5; }
code, pre { font-family: Consolas, monospace; }
code { background: #edf3f8; padding: 1px 4px; border-radius: 3px; }
pre { background: #f3f6fa; color: #233e52; padding: 16px; border: 1px solid #d8e2ed; border-radius: 6px; white-space: pre-wrap; overflow-wrap: anywhere; }
.tabs { display: flex; flex-wrap: wrap; gap: 7px; margin: 16px 0; }
button { font: inherit; cursor: pointer; padding: 9px 12px; border: 1px solid #829bb1; background: white; color: #17374f; border-radius: 6px; }
button[aria-selected="true"] { background: #075c52; color: white; border-color: #075c52; }
:focus-visible { outline: 3px solid #b85e00; outline-offset: 3px; }
.comparison { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.6fr); gap: 20px; }
.comparison > div { min-width: 0; }
details { margin: 16px 0; }
summary { cursor: pointer; font-weight: 600; }
[hidden] { display: none !important; }
footer { padding: 16px 0 32px; color: #4b6074; }
.relationship-section { --diagram-bg: #fff; --diagram-fg: #172c40; --diagram-border: #70879a; --json-fill: #fff0b3; }
.diagram-scroll { overflow-x: auto; border: 1px solid var(--diagram-border); border-radius: 8px; background: var(--diagram-bg); }
.class-diagram { display: block; width: 100%; min-width: 1360px; height: auto; font-size: 16px; }
.class-diagram text { fill: var(--diagram-fg); }
.class-box { fill: var(--diagram-bg); stroke: var(--diagram-border); stroke-width: 1.5; }
.class-divider { stroke: var(--diagram-border); }
.class-name { font: bold 19px Consolas, monospace; }
.class-translation { font-size: 16px; }
.column-label, .column-type { font: 15px Consolas, monospace; }
.column-key { font: bold 13px Consolas, monospace; }
.json-column { fill: var(--json-fill); }
.json-group rect { fill: none; stroke: var(--diagram-border); stroke-width: 2; stroke-dasharray: 9 6; }
.json-group text { font-size: 16px; }
.one-many { color: #175ca4; }
.one-one { color: #08745e; }
.edge { fill: none; stroke: currentColor; stroke-width: 2.5; }
.one-one .edge { stroke-dasharray: 8 4; }
.relationship text { fill: currentColor; paint-order: stroke; stroke: var(--diagram-bg); stroke-width: 5px; stroke-linejoin: round; }
.multiplicity { font-weight: 700; }
.measurement { font-size: 15px; }
.diagram-legend { display: flex; flex-wrap: wrap; gap: 12px 24px; }
.diagram-legend span { display: inline-flex; align-items: center; gap: 8px; font-weight: 600; }
.diagram-legend i { display: inline-block; width: 34px; border-top: 3px solid currentColor; }
.diagram-legend .one-one i { border-top-style: dashed; }
@media(max-width: 800px) { main { padding: 12px; } header, main > section { padding: 16px; } .comparison { grid-template-columns: 1fr; } }
@media (prefers-color-scheme: dark) {
  :root { color-scheme: dark; color: #e2edf5; background: #101820; }
  header, main > section, button { background: #18242e; color: #e2edf5; border-color: #52677b; }
  a { color: #8ac6ff; }
  .muted, footer, .eyebrow { color: #bacbd9; }
  caption, th, code, pre { background: #243644; color: #e2edf5; }
  td, th, .table-scroll, pre { border-color: #52677b; }
  tbody tr:nth-child(even) { background: #1d2c38; } tbody tr:hover { background: #264338; }
  .metric { background: #183b35; border-color: #48776e; } .metric strong, .pass { color: #7de2bd; }
  .notice { background: #3d321b; border-color: #e3b65e; } .fail { color: #ffadb3; }
  .relationship-section { --diagram-bg: #18242e; --diagram-fg: #e2edf5; --diagram-border: #8da6ba; --json-fill: #614c16; }
  .one-many { color: #8ac6ff; } .one-one { color: #7de2bd; }
}
@media print { body { background: white; } nav, .tabs { display: none; } .table-panel[hidden] { display: block !important; } .table-scroll { overflow: visible; } }
"""

JS = """
const buttons = [...document.querySelectorAll('.tabs button')];
const panels = [...document.querySelectorAll('.table-panel')];
document.querySelector('.tabs').setAttribute('role', 'tablist');
function selectTab(button, focus = false) {
  for (const candidate of buttons) {
    const active = candidate === button;
    candidate.setAttribute('role', 'tab');
    candidate.setAttribute('aria-selected', String(active));
    candidate.tabIndex = active ? 0 : -1;
  }
  for (const panel of panels) {
    panel.setAttribute('role', 'tabpanel');
    panel.hidden = panel.id !== button.getAttribute('aria-controls');
  }
  if (focus) button.focus();
}
for (const [index, button] of buttons.entries()) {
  button.addEventListener('click', () => selectTab(button));
  button.addEventListener('keydown', event => {
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % buttons.length;
    if (event.key === 'ArrowLeft') next = (index + buttons.length - 1) % buttons.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = buttons.length - 1;
    if (next !== undefined) { event.preventDefault(); selectTab(buttons[next], true); }
  });
}
selectTab(buttons[0]);
"""


def render_html(lab: dict, report: dict) -> str:
    """Sinh trang tiếng Việt tự chứa; mọi số liệu lấy từ kết quả phân tích."""
    analysis = report["lab"]
    queries = analysis["queries"]
    failed = sum(not check["ok"] for check in analysis["checks"])
    parts = ['<!doctype html><html lang="vi"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             f'<title>Khám phá dữ liệu · CS5104 Đề 1</title><style>{CSS}</style></head><body><main>',
             '<header><p class="eyebrow">CS5104 · ĐỀ 1 · SEED 731905</p><h1>Hồ sơ khám bệnh liên tỉnh</h1>',
             '<p>Khám phá dữ liệu gốc trước khi chốt phân tán. 10 bảng, 4 trạm; dữ liệu giả lập. Không sinh lại, không thay đổi CSV.</p>',
             '<p class="muted">Đọc offline bằng trình duyệt. CSS/JS và mẫu dữ liệu nằm trong file này; không cần mạng hay máy chủ.</p>',
             '<nav aria-label="Mục lục"><a href="#relationships">Sơ đồ quan hệ</a><a href="#schema">Lược đồ</a><a href="#tables">10 bảng dữ liệu</a><a href="#json">JSON ↔ quan hệ</a><a href="#regions">Phân bố vùng</a><a href="#decisions">Điểm cần chốt</a><a href="#checks">Kiểm chứng</a></nav>',
             '<div class="metrics">']
    for value, label in [(analysis["rows"]["patient"], "bệnh nhân · lab"), (analysis["rows"]["visit"], "lượt khám · lab"),
                         (analysis["cross_site"], "lượt khám liên vùng"), (analysis["json_check"]["mismatch_rows"], "dòng JSON/quan hệ lệch")]:
        parts.append(f'<div class="metric"><strong>{display(value)}</strong>{escape(label)}</div>')
    parts.append(f'</div><p class="{"fail" if failed else "pass"}">{failed} kiểm chứng thất bại trên bộ lab.</p></header>')
    parts.append(relationship_section(analysis["relationships"]))
    parts.extend(['<section id="schema"><h2>Lược đồ và quan hệ</h2>',
                  '<p>Nguồn: <code>project1.pdf</code>, trang 6–8, Hình 1.1 và bảng giải thích. Kiểu SQL giữ nguyên theo đề, không tự thêm precision hoặc ràng buộc NOT NULL.</p>'])
    relations = []
    for table in SCHEMA:
        foreign = "; ".join(f"{column} tham chiếu {parent}.{PRIMARY_KEYS[parent][0]}" for column, parent in FOREIGN_KEYS.get(table, [])) or "—"
        mapping = ("Bản quan hệ của visit.result" if table in RELATIONAL else "Chứa JSON: result" if table == "visit" else "Bảng nghiệp vụ")
        relations.append((table, ", ".join(PRIMARY_KEYS[table]), foreign, mapping))
    parts.append(html_table(["Bảng", "PK", "FK", "Vai trò JSON"], relations, "Khoá theo lược đồ tập trung"))
    parts.extend(['<p><code>patient</code> và <code>hospital</code> có quan hệ 1–N với <code>visit</code>; <code>visit</code> và <code>drug</code> có quan hệ 1–N với <code>prescription</code>. Mỗi bảng specialty nối 1–0..1 với <code>visit</code>. Hai bảng mảng nối 1–N với bảng specialty cha.</p>',
                  '<p class="notice">Đề không ghi đơn vị cho va_left, va_right, wbc, rbc, glucose. Trang không tự gán đơn vị y khoa hoặc đổi thang đo. value dùng unit của chính dòng xét nghiệm.</p></section>',
                  '<section id="tables"><h2>Khám phá từng bảng</h2><p>Mỗi bảng gồm mô tả nghiệp vụ, từ điển cột, các quan hệ theo sơ đồ và 10 dòng mẫu lab đầu tiên theo thứ tự CSV. NULL là ô CSV rỗng.</p>',
                  '<noscript><p class="notice">JavaScript đang tắt: mọi bảng vẫn đọc được; tab không hoạt động.</p></noscript>',
                  '<div class="tabs" aria-label="Chọn bảng">'])
    for table in SCHEMA:
        parts.append(f'<button type="button" id="tab-{table}" aria-controls="panel-{table}">{table}</button>')
    parts.append('</div>')
    parts.extend(table_panel(table, lab, analysis["relationships"]) for table in SCHEMA)
    parts.append('</section><section id="json"><h2>visit.result ↔ bản quan hệ</h2>')
    parts.append('<p>Kiểm tra toàn bộ lab, không chỉ ví dụ: đúng tập khoá JSON, kiểu dữ liệu, trường lồng ecg, thứ tự diagnoses theo seq, tests theo code; tìm dòng thiếu, thừa, sai giá trị. Thứ tự tests không được lưu trong lược đồ nên không dùng để so sánh.</p>')
    check = analysis["json_check"]
    matched = check["visits_checked"] - check["mismatch_visits"]
    parts.append(f'<h3>lab: {display(matched)}/{display(check["visits_checked"])} lượt khớp ({matched / check["visits_checked"]:.2%})</h3>')
    parts.append(html_table(["Bảng", "Dòng từ JSON", "Dòng CSV", "Thiếu", "Thừa", "Sai giá trị", "Tổng dòng lệch"],
                            [(table, values["expected"], values["actual"], values["missing"], values["extra"], values["changed"], values["mismatch_rows"])
                             for table, values in check["tables"].items()], "Đối chiếu hai chiều: lab"))
    if check["invalid_json_count"] or check["mismatch_rows"]:
        parts.append(f'<pre class="fail">{escape(json_text(check, True))}</pre>')
    for specialty in SPECIALTIES:
        visit = next(row for row in lab["visit"] if row["specialty"] == specialty)
        parts.append(f'<h3>Ví dụ lab: {specialty} · visit_id = {visit["visit_id"]}</h3><div class="comparison"><div><h4>JSON gốc</h4>')
        parts.append(f'<pre>{escape(json_text(visit["result"], True))}</pre></div><div><h4>Dòng CSV tương ứng</h4>')
        for table in RELATIONAL:
            if table == f"visit_{specialty}" or table.startswith(f"visit_{specialty}_"):
                columns = [column[0] for column in SCHEMA[table][1]]
                parts.append(html_table(columns, [[row[column] for column in columns] for row in lab[table] if row["visit_id"] == visit["visit_id"]], table, raw=True))
        parts.append('</div></div>')
    parts.append('</section><section id="regions"><h2>Phân bố vùng · lab</h2>')
    parts.append(regional_table(analysis["regions"], "Tỉnh cư trú khác tỉnh bệnh viện; prescription đếm theo tỉnh bệnh nhân của visit"))
    parts.append(regional_table(analysis["matrix"], "Ma trận visit: hàng = patient.home_province, cột = hospital.province"))
    parts.append(f'<p>Liên vùng: <strong>{display(analysis["cross_site"])}</strong> lượt ({analysis["cross_rate"]:.4%}); <strong>{display(analysis["cross_patients"])}</strong> bệnh nhân từng khám ngoài tỉnh.</p>')
    parts.append(regional_table({specialty: {site: analysis["specialties"][site][specialty] for site in SITES} for specialty in SPECIALTIES}, "Specialty theo tỉnh cư trú bệnh nhân"))
    parts.append(regional_table(analysis["months"], "visit theo tháng visit_date và tỉnh cư trú bệnh nhân"))
    parts.append('</section><section id="decisions"><h2>Điểm cần chốt</h2>')
    parts.append('<p class="notice">Các phương án dưới đây chỉ cung cấp số liệu để review, không tự chốt thiết kế hoặc thay đổi NOTES.md.</p><h3>Q2 · Tiền thuốc năm 2025</h3>')
    parts.append('<p>Join <code>prescription → visit → patient</code> và <code>prescription → drug</code>; lọc <code>2025-01-01 ≤ visit_date &lt; 2026-01-01</code>, nhóm theo home_province. A = SUM(quantity × price); B = SUM(quantity × price × days). Đơn vị hiển thị: đồng. Tính chính xác bằng Decimal, không float.</p>')
    q2_rows = [(site, queries["Q2"][site]["A"], queries["Q2"][site]["B"]) for site in SITES]
    q2_rows.append(("Tổng", sum(values["A"] for values in queries["Q2"].values()), sum(values["B"] for values in queries["Q2"].values())))
    parts.append(html_table(["home_province", "Cách A (đồng)", "Cách B (đồng)"], q2_rows, "Hai cách hiểu quantity trong Q2"))
    parts.append('<p><strong>Cần chốt:</strong> quantity là tổng số lượng hay số lượng mỗi ngày? Chỉ B nhân days. Không suy ra ý nghĩa này từ dữ liệu ngẫu nhiên.</p><h3>Q1 và Q3 · Tháng 3/2026</h3>')
    parts.append(html_table(["specialty", "Số lượt Q1"], [*queries["Q1"].items(), ("Tổng", queries["Q1_total"])], "Q1: patient.home_province = tayninh; mọi bệnh viện"))
    parts.append(html_table(["home_province", "Số lượt Q3"], [*queries["Q3"].items(), ("Tổng", queries["Q3_total"])], "Q3: hospital.province = tayninh; mọi tỉnh bệnh nhân"))
    parts.append(f'<p>Trong Q3 có {display(queries["Q3_total"] - queries["Q3"]["tayninh"])} lượt của bệnh nhân ngoài Tây Ninh.</p>')
    parts.append('<p>Hai truy vấn đếm lượt, không đếm bệnh nhân distinct. Chia visit theo tỉnh cư trú giữ Q1 local; Q3 cần lấy lượt khám của bệnh nhân ở trạm khác. Trang tính số liệu, chưa kiểm chứng EXPLAIN PostgreSQL.</p><h3>Q4 = Q5?</h3>')
    parts.append(html_table(["Q4 từ JSON", "Q5 từ visit_cardio", "Cùng tập patient_id?", "Chỉ Q4", "Chỉ Q5"],
                            [(queries["Q4"], queries["Q5"], queries["Q4_Q5_equal"], len(queries["Q4_only"]), len(queries["Q5_only"]))], "Bệnh nhân distinct, cardio bp_systolic ≥ 140, toàn bộ thời gian"))
    parts.append('<h3>Cấp phát 4 trạm lên 2 máy</h3><p>Phương án đang review: patient theo home_province; visit và mọi bảng con theo bệnh nhân của visit. Mỗi trạm có đủ 30 hospital và 500 drug; tính cả các bản sao. Không tạo mảnh hoặc sửa dữ liệu gốc.</p>')
    site_rows = {table: {site: analysis["site_rows"][site][table] for site in SITES} for table in SCHEMA}
    site_rows["Tổng mỗi trạm"] = analysis["site_totals"]
    parts.append(regional_table(site_rows, "Số dòng từng bảng sau phân mảnh và sao chép"))
    parts.append(html_table(["Phương án", "Trạm máy A", "Dòng máy A", "Trạm máy B", "Dòng máy B"],
                            [(plan["option"], ", ".join(plan["A_sites"]), plan["A_rows"], ", ".join(plan["B_sites"]), plan["B_rows"]) for plan in analysis["machine_plans"]], "Ba phương án cấp phát (chưa chọn)"))
    parts.append(f'<p>Tập trung: {display(sum(analysis["rows"].values()))} dòng; phân tán: {display(sum(analysis["site_totals"].values()))} dòng, tăng {display(3 * (analysis["rows"]["hospital"] + analysis["rows"]["drug"]))} do sao chép. Chỉ đếm dòng; không phản ánh byte, index, tải truy vấn hoặc bản CSDL đối chứng, không cộng giao diện/dashboard.</p>')
    parts.append('<h3>Khoá chính hiện tại</h3>')
    parts.append(html_table(["Bảng", "Max id lab"], analysis["max_ids"].items(), "Mốc để xem xét sequence/dải ID cho dòng mới"))
    parts.append('<p>Cần chốt sequence bước 4 hay dải ID riêng và quy ước site_no. Trang chỉ báo max hiện có; không cấp phát ID mới.</p><h3>Bất thường và điểm dễ hiểu nhầm</h3>')
    labels = {"visits_without_prescription": "Lượt khám không có dòng thuốc", "patients_without_visit": "Bệnh nhân chưa có lượt khám",
              "repeated_visit_drug_pairs": "Cặp (visit_id, drug_code) có nhiều dòng thuốc", "extra_repeated_drug_rows": "Dòng vượt quá dòng đầu ở các cặp thuốc lặp",
              "null_cells": "Ô CSV NULL trong toàn bộ lab"}
    parts.append(html_table(["Hiện tượng", "Số lượng lab"], [(labels[key], value) for key, value in analysis["anomalies"].items()], "Không bỏ hoặc gộp những dòng này khi tính"))
    parts.append('<p>Các cặp thuốc lặp vẫn có prescription_id riêng, không vi phạm PK theo đề. Q2 cộng từng dòng, không DISTINCT theo visit_id/drug_code. Các lượt chưa có thuốc và bệnh nhân chưa khám không phải FK lỗi.</p>')
    parts.append('</section><section id="checks"><h2>Kiểm chứng và khả năng tái lập</h2>')
    parts.append('<p>Đọc lại summary.json của bộ lab: số dòng 10 bảng, phân bố patient/hospital, cross_site, tỷ lệ làm tròn 4 chữ số và specialty. <strong>summary.json không chứa Q1/Q3</strong>; hai mốc 1.464/1.436 lấy từ task, tính lại từ CSV. PK/FK được kiểm tra trước mọi phép join; lỗi cấu trúc CSV dừng script, không bỏ dòng.</p>')
    parts.append(html_table(["Kiểm tra", "Tính từ CSV / thực tế", "Tham chiếu / kỳ vọng", "Kết quả"],
                            [(check["label"], check["actual"], check["expected"], "PASS" if check["ok"] else "FAIL") for check in analysis["checks"]], "Kiểm chứng lab"))
    parts.append(f'<p>Python chạy lần sinh trang này: <code>{escape(report["metadata"]["python"])}</code>. Script dùng API chuẩn tương thích Python 3.12, không dependency ngoài. Thứ tự hiển thị cố định; không dùng random hoặc thời gian hiện tại.</p>')
    parts.append('<p>Chạy lại: <code>python scripts/explore_data.py</code>. Tự kiểm tra logic và các tình huống dữ liệu hỏng: <code>python scripts/explore_data.py --self-test</code>. Trang được ghi nguyên tử; lỗi kiểm chứng vẫn được ghi trong trang và script trả mã lỗi.</p>')
    parts.append('<details><summary>SHA-256 của 10 CSV và 1 summary.json đầu vào</summary>')
    parts.append(html_table(["File", "SHA-256"], report["metadata"]["sha256"].items(), "Dấu kiểm dữ liệu nguồn"))
    parts.append('</details></section><footer>CS5104 · Dữ liệu giả lập · Tự chứa, không CDN · Kiểu SQL theo đề, không suy diễn đơn vị thiếu.</footer></main>')
    embedded = json_text(report).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    parts.append(f'<script id="report-data" type="application/json">{embedded}</script><script>{JS}</script></body></html>')
    return "\n".join(parts)


def test_relationship_diagram(relations: list[dict]) -> None:
    """Kiểm tra 9 FK, số đo lab, số 0, SVG và đường không xuyên hộp."""
    sparse = {table: [] for table in SCHEMA}
    sparse.update(hospital=[{"hospital_id": 1}, {"hospital_id": 2}],
                  patient=[{"patient_id": 1}, {"patient_id": 2}],
                  drug=[{"drug_code": "A"}, {"drug_code": "B"}],
                  visit=[{"visit_id": 1, "patient_id": 1, "hospital_id": 1, "specialty": "cardio"},
                         {"visit_id": 2, "patient_id": 1, "hospital_id": 1, "specialty": "eye"}],
                  prescription=[{"prescription_id": number, "visit_id": 1, "drug_code": "A"} for number in (1, 2, 3)],
                  visit_cardio=[{"visit_id": 1}], visit_eye=[{"visit_id": 2}])
    measured = {(row["parent"], row["child"]): row for row in relationship_stats(sparse)}
    assert measured["patient", "visit"]["range"] == (0, 2)
    assert measured["visit", "prescription"]["range"] == (0, 3)
    assert measured["drug", "prescription"]["range"] == (0, 3)
    assert measured["visit_eye", "visit_eye_diagnosis"]["range"] == (0, 0)
    assert ("patient", "hospital") not in measured
    assert ("visit", "drug") not in measured
    assert all(row["range"] == row["reverse_range"] == (0, 0)
               for row in relationship_stats({table: [] for table in SCHEMA}))
    measured = {(row["parent"], row["child"]): row for row in relations}
    expected = {("hospital", "visit"): (828, 10328), ("patient", "visit"): (0, 15),
                ("visit", "prescription"): (0, 12), ("drug", "prescription"): (33, 38546),
                ("visit_eye", "visit_eye_diagnosis"): (1, 3), ("visit_blood", "visit_blood_test"): (1, 4),
                **{("visit", f"visit_{specialty}"): (0, 1) for specialty in SPECIALTIES}}
    assert len(relations) == 9 and set(measured) == set(expected)
    assert Counter(row["kind"] for row in relations) == {"1-n": 6, "1-1": 3}
    assert {(row["parent"], row["child"], row["fk"]) for row in relations} == {
        (parent, child, f"{child}.{column}") for child, references in FOREIGN_KEYS.items() for column, parent in references}
    for pair, limits in expected.items():
        assert measured[pair]["range"] == limits, (pair, measured[pair]["range"], limits)
        assert measured[pair]["reverse_range"] == (1, 1)
    assert measured["patient", "visit"]["zeros"] == 375
    assert measured["visit", "prescription"]["zeros"] == 6456
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    diagram = ElementTree.fromstring(relationship_diagram(relations))
    assert diagram.attrib["viewBox"] == "0 0 1680 1380"
    boxes = {}
    for group in diagram.findall("svg:g[@class='diagram-class']", namespace):
        table = group.attrib["data-table"]
        rectangle = group.find("svg:rect", namespace)
        boxes[table] = tuple(float(rectangle.attrib[key]) for key in ("x", "y", "width", "height"))
        names = [element.text for element in group.findall("svg:text[@class='column-label']", namespace)]
        types = [element.text for element in group.findall("svg:text[@class='column-type']", namespace)]
        keys = [element.text or "" for element in group.findall("svg:text[@class='column-key']", namespace)]
        assert names == [column[0] for column in SCHEMA[table][1]]
        assert types == [column[1] for column in SCHEMA[table][1]]
        for column, role in zip(names, keys):
            assert ("PK" in role) == (column in PRIMARY_KEYS[table])
            assert ("FK" in role) == any(column == foreign for foreign, parent in FOREIGN_KEYS.get(table, []))
        assert len(group.findall("svg:rect[@class='json-column']", namespace)) == int(table == "visit")
    assert set(boxes) == set(SCHEMA)
    frame = diagram.find("svg:g[@class='json-group']/svg:rect", namespace)
    frame_x, frame_y, frame_width, frame_height = (float(frame.attrib[key]) for key in ("x", "y", "width", "height"))
    for table, (left, top, width, height) in boxes.items():
        inside = frame_x < left and left + width < frame_x + frame_width and frame_y < top and top + height < frame_y + frame_height
        assert inside == (table in RELATIONAL)
    edges = diagram.findall("svg:g[@data-kind]", namespace)
    assert len(edges) == 9
    assert {(group.attrib["data-parent"], group.attrib["data-child"]) for group in edges} == set(expected)
    for group in edges:
        parent, child = group.attrib["data-parent"], group.attrib["data-child"]
        points = [tuple(map(float, point.split(','))) for point in group.find("svg:polyline", namespace).attrib["points"].split()]
        for table, (horizontal, vertical) in ((parent, points[0]), (child, points[-1])):
            left, top, width, height = boxes[table]
            assert ((horizontal in (left, left + width) and top <= vertical <= top + height)
                    or (vertical in (top, top + height) and left <= horizontal <= left + width))
        for (start_x, start_y), (end_x, end_y) in zip(points, points[1:]):
            assert start_x == end_x or start_y == end_y
            for table, (left, top, width, height) in boxes.items():
                if start_x == end_x:
                    crosses = left < start_x < left + width and max(min(start_y, end_y), top) < min(max(start_y, end_y), top + height)
                else:
                    crosses = top < start_y < top + height and max(min(start_x, end_x), left) < min(max(start_x, end_x), left + width)
                assert not crosses, (parent, child, table)
        assert [element.text for element in group.findall("svg:text[@class='multiplicity']", namespace)] == list(measured[parent, child]["ends"])
    print("PASS: 10 class, đúng 9 FK trực tiếp, số đo lab, cha có 0 con, PK/FK, nhóm JSON, cạnh trực giao không xuyên hộp.")


def test_table_panels(lab: dict, analysis: dict) -> None:
    """Kiểm tra 10 tab chỉ có từ điển, đủ quan hệ và đúng 10 mẫu lab."""
    for table, (_, columns) in SCHEMA.items():
        panel = ElementTree.fromstring(table_panel(table, lab, analysis["relationships"]))
        tables = panel.findall("div/table")
        assert len(tables) == 3
        dictionary, relations, samples = tables
        dictionary_rows = dictionary.findall("tbody/tr")
        assert len(dictionary_rows) == len(columns)
        for row, (name, sql_type, meaning, unit) in zip(dictionary_rows, columns):
            cells = [cell.text or "" for cell in row.findall("td")]
            assert cells[:4] == [name, sql_type, meaning, unit]
            assert ("PK" in cells[4]) == (name in PRIMARY_KEYS[table])
            for column, parent in FOREIGN_KEYS.get(table, []):
                if column == name:
                    assert f"FK: {parent}.{PRIMARY_KEYS[parent][0]}" in cells[4]
        related = [relation for relation in analysis["relationships"]
                   if table in (relation["parent"], relation["child"])]
        relation_rows = relations.findall("tbody/tr")
        assert len(relation_rows) == len(related)
        for row, relation in zip(relation_rows, related):
            cells = [cell.text for cell in row.findall("td")]
            assert cells[1:4] == [relation["parent"], relation["child"], relation["fk"]]
            assert cells[5] == " — ".join(relation["ends"])
            assert cells[4] == relation["kind"]
            assert cells[0] == ("Cha" if table == relation["parent"] else "Con")
        sample_rows = samples.findall("tbody/tr")
        assert len(sample_rows) == 10
        for row, source in zip(sample_rows, lab[table][:10]):
            expected = [json_text(source[column[0]]) if isinstance(source[column[0]], dict)
                        else str(source[column[0]]) if source[column[0]] is not None else "NULL" for column in columns]
            assert [cell.text or "" for cell in row.findall("td")] == expected
    document = render_html(lab, {"lab": analysis, "metadata": {"python": platform.python_version(), "sha256": {}}})
    assert "mini" not in document.casefold()
    assert "n-n" not in document.casefold()
    assert "many-many" not in document
    assert "Thống kê toàn bộ lab:" not in document
    assert "Ví dụ lab</th>" not in document
    assert "row-filter" not in document
    assert document.count('class="table-panel"') == 10
    print("PASS: 10 tab, từ điển PK/FK, chỉ quan hệ FK trực tiếp, 10 mẫu lab/tab, không dữ liệu phụ hoặc thống kê cột.")


def self_test() -> None:
    """Kiểm tra lab và các bản sao nhỏ sửa trong RAM; không chạm dữ liệu gốc."""
    lab, summary = load_dataset(DATA / "lab")
    baseline = analyze(lab, summary)
    assert all(check["ok"] for check in baseline["checks"])
    assert baseline["json_check"]["mismatch_rows"] == 0
    assert parse_value("0.10", "numeric") == Decimal("0.10")
    assert parse_value("", "numeric") is None
    assert parse_json_value("", "text") == ""
    selected = {next(row["visit_id"] for row in lab["visit"] if row["specialty"] == specialty
                     and (specialty != "eye" or len(row["result"]["diagnoses"]) > 1)) for specialty in SPECIALTIES}
    selected.add(lab["prescription"][0]["visit_id"])
    fixture = {"visit": [row for row in lab["visit"] if row["visit_id"] in selected],
               "prescription": lab["prescription"][:1]}
    for table in RELATIONAL:
        fixture[table] = [row for row in lab[table] if row["visit_id"] in selected]
    for table, column, children in (("patient", "patient_id", "visit"), ("hospital", "hospital_id", "visit"),
                                     ("drug", "drug_code", "prescription")):
        keys = {row[column] for row in fixture[children]}
        fixture[table] = [row for row in lab[table] if row[column] in keys]
    fixture_baseline = analyze(fixture, summary)

    def must_fail(action: object) -> None:
        try:
            action()
        except (ValueError, InvalidOperation):
            return
        raise AssertionError("Dữ liệu hỏng phải báo lỗi")

    for value, sql_type in [("32768", "smallint"), ("1.5", "integer"), ("NaN", "numeric"),
                            ("2025-02-30", "date"), ('{"value": NaN}', "jsonb"),
                            ('{"value": 1, "value": 2}', "jsonb")]:
        must_fail(lambda: parse_value(value, sql_type))
    must_fail(lambda: parse_json_value("142", "smallint"))
    must_fail(lambda: parse_json_value(True, "smallint"))
    changed = deepcopy(fixture)
    changed["visit_cardio"][0]["bp_systolic"] += 1
    assert reconcile_json(changed)["tables"]["visit_cardio"]["changed"] == 1
    changed = deepcopy(fixture)
    changed["visit_eye_diagnosis"].pop()
    assert reconcile_json(changed)["tables"]["visit_eye_diagnosis"]["missing"] == 1
    changed = deepcopy(fixture)
    changed["visit_blood_test"].append({**changed["visit_blood_test"][0], "code": "EXTRA"})
    assert reconcile_json(changed)["tables"]["visit_blood_test"]["extra"] == 1
    changed = deepcopy(fixture)
    eye_visit = next(row for row in changed["visit"] if row["specialty"] == "eye" and len(row["result"]["diagnoses"]) > 1)
    eye_visit["result"]["diagnoses"].reverse()
    assert reconcile_json(changed)["tables"]["visit_eye_diagnosis"]["changed"] >= 2
    changed = deepcopy(fixture)
    blood_visit = next(row for row in changed["visit"] if row["specialty"] == "blood")
    blood_visit["result"]["tests"].reverse()
    assert reconcile_json(changed)["mismatch_rows"] == 0
    blood_visit["result"]["tests"].append(blood_visit["result"]["tests"][0])
    assert reconcile_json(changed)["invalid_json_count"] == 1
    changed = deepcopy(fixture)
    changed["visit"][0]["result"]["unexpected"] = 1
    assert reconcile_json(changed)["invalid_json_count"] == 1
    changed = deepcopy(fixture)
    changed["patient"].append(changed["patient"][0])
    must_fail(lambda: validate_relations(changed))
    changed = deepcopy(fixture)
    changed["prescription"][0]["visit_id"] = -1
    must_fail(lambda: validate_relations(changed))
    changed = deepcopy(fixture)
    prescription = changed["prescription"][0]
    changed["prescription"] = [prescription]
    prescription.update(quantity=3, days=7)
    next(row for row in changed["drug"] if row["drug_code"] == prescription["drug_code"])["price"] = Decimal("0.10")
    visit = next(row for row in changed["visit"] if row["visit_id"] == prescription["visit_id"])
    visit["visit_date"] = "2025-12-31"
    home = next(row["home_province"] for row in changed["patient"] if row["patient_id"] == visit["patient_id"])
    result = analyze(changed, summary)
    assert result["queries"]["Q2"][home] == {"A": Decimal("0.30"), "B": Decimal("2.10")}
    assert not all(check["ok"] for check in result["checks"])
    visit["visit_date"] = "2026-01-01"
    result = analyze(changed, summary)
    assert all(values["A"] == values["B"] == 0 for values in result["queries"]["Q2"].values())
    assert "<script>" not in html_table(["text"], [("<script>",)], "<script>")
    assert analyze(fixture, summary) == fixture_baseline
    print("PASS: lab, NULL, kiểu/miền, Decimal, mốc năm, PK/FK, JSON thiếu/thừa/sai/thứ tự, escape HTML.")
    test_relationship_diagram(baseline["relationships"])
    test_table_panels(lab, baseline)


def main() -> int:
    """Chạy self-test hoặc tạo HTML; trả mã 1 nếu đọc/kiểm chứng thất bại."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="Kiểm tra logic, không ghi HTML hoặc dữ liệu")
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
        return 0
    paths = [DATA / "lab" / name for name in [*(f"{table}.csv" for table in SCHEMA), "summary.json"]]
    fingerprints = {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    report = {"metadata": {"python": platform.python_version(), "seed": 731905,
                            "schema_source": "project1.pdf, trang 6–8", "sha256": fingerprints}}
    lab, summary = load_dataset(DATA / "lab")
    report["lab"] = analyze(lab, summary)
    document = render_html(lab, report).encode("utf-8")
    if len(document) >= 15_000_000:
        raise ValueError(f"HTML {len(document)} byte vượt giới hạn < 15 MB")
    for path in paths:
        key = str(path.relative_to(ROOT)).replace("\\", "/")
        if hashlib.sha256(path.read_bytes()).hexdigest() != fingerprints[key]:
            raise ValueError(f"Nguồn đã đổi trong lúc chạy: {path}; không ghi HTML")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=OUTPUT.parent, suffix=".tmp", delete=False) as destination:
            temporary = Path(destination.name)
            destination.write(document)
        os.replace(temporary, OUTPUT)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    failed = [check for check in report["lab"]["checks"] if not check["ok"]]
    print(f"HTML: {OUTPUT}\nKích thước: {len(document)} byte ({len(document) / 1_000_000:.3f} MB)")
    print(json_text({key: report["lab"][key] for key in ("queries", "site_totals", "machine_plans", "max_ids", "anomalies")}, True))
    for check in failed:
        print(f"FAIL lab: {json_text(check)}", file=sys.stderr)
    print(f"Kiểm chứng: {len(report['lab']['checks'])} kiểm tra; {len(failed)} lỗi.")
    return int(bool(failed))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError, KeyError, InvalidOperation, csv.Error) as error:
        print(f"LỖI: {error}", file=sys.stderr)
        raise SystemExit(1) from error
