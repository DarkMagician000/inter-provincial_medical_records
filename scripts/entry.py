#!/usr/bin/env python3
"""Giao diện nhập thẳng vào trạm cư trú; --selftest không cần PostgreSQL."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from functools import partial
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import random
import secrets
import time
import tomllib
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit


PROVINCES = {
    "tayninh": "Tây Ninh", "hcm": "TP. Hồ Chí Minh",
    "cantho": "Cần Thơ", "dongnai": "Đồng Nai",
}
SPECIALTIES = {"cardio": "Tim mạch", "eye": "Mắt", "blood": "Máu"}
EYE_DX = ("myopia", "hyperopia", "astigmatism", "cataract", "glaucoma",
          "dry_eye", "conjunctivitis")
BLOOD_TESTS = {
    "ALT": ("U/L", 10, 80), "AST": ("U/L", 10, 80),
    "HbA1c": ("%", 4.5, 10), "CHOL": ("mmol/L", 3, 8),
    "TG": ("mmol/L", 0.5, 4), "CREA": ("umol/L", 50, 150),
}
RHYTHMS = ("sinus", "afib", "brady", "tachy")
FIELDS = {
    "cardio": (
        ("bp_systolic", "Huyết áp tâm thu (mmHg)", 90, 200, 0, 128),
        ("bp_diastolic", "Huyết áp tâm trương (mmHg)", 50, 120, 0, 80),
        ("heart_rate", "Nhịp tim (lần/phút)", 45, 140, 0, 76),
        ("ecg_qt_ms", "Khoảng QT (ms)", 340, 480, 0, 400),
    ),
    "eye": (
        ("va_left", "Thị lực mắt trái", 1, 10, 1, 8),
        ("va_right", "Thị lực mắt phải", 1, 10, 1, 8),
        ("iop_mmhg", "Nhãn áp (mmHg)", 10, 30, 0, 18),
    ),
    "blood": (
        ("wbc", "Bạch cầu (wbc)", 3.5, 12, 2, 7),
        ("rbc", "Hồng cầu (rbc)", 3.5, 6, 2, 4.5),
        ("glucose", "Đường huyết (glucose)", 3.8, 12, 2, 5.5),
    ),
}
RELATIONAL_SQL = {
    "visit_cardio": "INSERT INTO visit_cardio "
        "(visit_id, bp_systolic, bp_diastolic, heart_rate, ecg_rhythm, ecg_qt_ms) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
    "visit_eye": "INSERT INTO visit_eye (visit_id, va_left, va_right, iop_mmhg) "
        "VALUES (%s, %s, %s, %s)",
    "visit_eye_diagnosis": "INSERT INTO visit_eye_diagnosis "
        "(visit_id, seq, diagnosis) VALUES (%s, %s, %s)",
    "visit_blood": "INSERT INTO visit_blood (visit_id, wbc, rbc, glucose) "
        "VALUES (%s, %s, %s, %s)",
    "visit_blood_test": "INSERT INTO visit_blood_test "
        "(visit_id, code, value, unit) VALUES (%s, %s, %s, %s)",
}


def number(value: Any, label: str, low: float, high: float,
           places: int = 0) -> int | float:
    """Đọc số hữu hạn đúng khoảng và độ chính xác; trả int hoặc float."""
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{label}: phải là số.") from None
    if not parsed.is_finite() or not Decimal(str(low)) <= parsed <= Decimal(str(high)):
        raise ValueError(f"{label}: phải nằm trong [{low}, {high}].")
    if parsed != round(parsed, places):
        raise ValueError(f"{label}: tối đa {places} chữ số thập phân.")
    return int(parsed) if places == 0 else float(parsed)


def text(value: Any, label: str, maximum: int = 200) -> str:
    """Đọc chuỗi không rỗng, có giới hạn độ dài."""
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label}: cần chuỗi dài 1–{maximum} ký tự.")
    return value.strip()


def choice(value: Any, choices: Any, label: str) -> str:
    """Chỉ nhận giá trị chuỗi thuộc danh sách cho phép."""
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"{label}: giá trị không hợp lệ.")
    return value


def object_rows(value: Any, label: str, maximum: int) -> list[dict]:
    """Kiểm tra danh sách các dòng nhập trước khi truy cập cột."""
    if (not isinstance(value, list) or len(value) > maximum
            or any(not isinstance(row, dict) for row in value)):
        raise ValueError(f"{label}: tối đa {maximum} dòng đối tượng.")
    return value


def parse_result(specialty: str, data: dict) -> dict:
    """Tạo jsonb từ trường đã kiểm tra, đúng kiểu và khoảng của bộ sinh."""
    specialty = choice(specialty, SPECIALTIES, "Chuyên khoa")
    result = {
        name: number(data.get(name), label, low, high, places)
        for name, label, low, high, places, default in FIELDS[specialty]
    }
    if specialty == "cardio":
        result["ecg"] = {
            "rhythm": choice(data.get("ecg_rhythm"), RHYTHMS, "Nhịp điện tim"),
            "qt_ms": result.pop("ecg_qt_ms"),
        }
    elif specialty == "eye":
        diagnoses = data.get("diagnoses")
        if isinstance(diagnoses, str):
            diagnoses = [item.strip() for item in diagnoses.split(",")]
        if not isinstance(diagnoses, list) or not 1 <= len(diagnoses) <= 3:
            raise ValueError("Chẩn đoán mắt: chọn 1–3 chẩn đoán.")
        diagnoses = [choice(item, EYE_DX, "Chẩn đoán mắt") for item in diagnoses]
        if len(set(diagnoses)) != len(diagnoses):
            raise ValueError("Chẩn đoán mắt không được trùng.")
        result["diagnoses"] = diagnoses
    else:
        tests = []
        for row in object_rows(data.get("tests"), "Xét nghiệm", 4):
            if all(row.get(key, "") == "" for key in ("code", "value", "unit")):
                continue
            code = choice(row.get("code"), BLOOD_TESTS, "Mã xét nghiệm")
            unit, low, high = BLOOD_TESTS[code]
            if row.get("unit") != unit:
                raise ValueError(f"{code}: đơn vị phải là {unit}.")
            tests.append({"code": code,
                          "value": number(row.get("value"), code, low, high, 2),
                          "unit": unit})
        if not tests or len({row["code"] for row in tests}) != len(tests):
            raise ValueError("Cần 1–4 xét nghiệm, không trùng mã.")
        result["tests"] = tests
    return result


def parse_visit(data: dict) -> dict:
    """Kiểm tra toàn bộ lượt nhập trước khi mở giao dịch ghi."""
    specialty = choice(data.get("specialty"), SPECIALTIES, "Chuyên khoa")
    try:
        visit_date = date.fromisoformat(text(data.get("visit_date"), "Ngày khám", 10))
    except ValueError:
        raise ValueError("Ngày khám: cần ngày hợp lệ dạng YYYY-MM-DD.") from None
    mode = choice(data.get("patient_mode"), ("new", "existing"), "Bệnh nhân")
    if mode == "new":
        patient = {
            "full_name": text(data.get("full_name"), "Họ tên"),
            "birth_year": number(data.get("birth_year"), "Năm sinh", 1, date.today().year),
            "gender": choice(data.get("gender"), ("M", "F"), "Giới tính"),
        }
    else:
        patient = {"patient_id": number(data.get("patient_id"), "patient_id", 1, 2147483647)}
    prescriptions = []
    for row in object_rows(data.get("prescriptions", []), "Đơn thuốc", 3):
        if all(row.get(key, "") == "" for key in ("drug_code", "quantity", "days")):
            continue
        prescriptions.append({
            "drug_code": text(row.get("drug_code"), "Mã thuốc", 100),
            "quantity": number(row.get("quantity"), "Số lượng thuốc", 1, 60),
            "days": number(row.get("days"), "Số ngày dùng thuốc", 1, 30),
        })
    return {
        "patient": patient, "specialty": specialty, "visit_date": visit_date,
        "hospital_id": number(data.get("hospital_id"), "Bệnh viện", 1, 2147483647),
        "result": parse_result(specialty, data), "prescriptions": prescriptions,
    }


def random_result(specialty: str, rng: random.Random) -> dict:
    """Sinh kết quả với cấu trúc, kiểu số và phân phối của generate.py."""
    choice(specialty, SPECIALTIES, "Chuyên khoa")
    if specialty == "cardio":
        return {
            "bp_systolic": int(round(min(200, max(90, rng.gauss(128, 18))))),
            "bp_diastolic": int(round(min(120, max(50, rng.gauss(80, 10))))),
            "heart_rate": int(round(min(140, max(45, rng.gauss(76, 12))))),
            "ecg": {"rhythm": rng.choices(RHYTHMS, (80, 6, 7, 7))[0],
                    "qt_ms": rng.randint(340, 480)},
        }
    if specialty == "eye":
        diagnoses = rng.sample(EYE_DX, rng.randint(1, 3))
        return {"va_left": round(rng.uniform(1, 10), 1),
                "va_right": round(rng.uniform(1, 10), 1),
                "iop_mmhg": rng.randint(10, 30), "diagnoses": diagnoses}
    tests = []
    for code in rng.sample(list(BLOOD_TESTS), rng.randint(1, 4)):
        unit, low, high = BLOOD_TESTS[code]
        tests.append({"code": code, "value": round(rng.uniform(low, high), 2), "unit": unit})
    return {"wbc": round(rng.uniform(3.5, 12), 2),
            "rbc": round(rng.uniform(3.5, 6), 2),
            "glucose": round(rng.uniform(3.8, 12), 2), "tests": tests}


def relational_rows(visit_id: int, specialty: str, result: dict) -> dict[str, list[tuple]]:
    """Chiếu cùng một jsonb thành các dòng quan hệ; seq mắt bắt đầu từ 1."""
    choice(specialty, SPECIALTIES, "Chuyên khoa")
    if specialty == "cardio":
        return {"visit_cardio": [(visit_id, result["bp_systolic"], result["bp_diastolic"],
                                  result["heart_rate"], result["ecg"]["rhythm"],
                                  result["ecg"]["qt_ms"])]}
    if specialty == "eye":
        return {
            "visit_eye": [(visit_id, result["va_left"], result["va_right"], result["iop_mmhg"])],
            "visit_eye_diagnosis": [(visit_id, seq, diagnosis)
                                    for seq, diagnosis in enumerate(result["diagnoses"], 1)],
        }
    return {
        "visit_blood": [(visit_id, result["wbc"], result["rbc"], result["glucose"])],
        "visit_blood_test": [(visit_id, row["code"], row["value"], row["unit"])
                             for row in result["tests"]],
    }


def insert_visit(connection: Any, patient_id: int, hospital_id: int,
                 specialty: str, visit_date: date, result: dict,
                 prescriptions: list[dict]) -> tuple[int, list[int]]:
    """Ghi lượt khám, bản quan hệ và thuốc trên giao dịch của bên gọi."""
    from psycopg.types.json import Jsonb

    visit_id = connection.execute(
        "INSERT INTO visit (visit_id, patient_id, hospital_id, specialty, visit_date, result) "
        "VALUES (nextval('visit_id_seq'), %s, %s, %s, %s, %s) RETURNING visit_id",
        (patient_id, hospital_id, specialty, visit_date, Jsonb(result)),
    ).fetchone()[0]
    with connection.cursor() as cursor:
        for table, rows in relational_rows(visit_id, specialty, result).items():
            cursor.executemany(RELATIONAL_SQL[table], rows)
    prescription_ids = []
    for row in prescriptions:
        prescription_ids.append(connection.execute(
            "INSERT INTO prescription (prescription_id, visit_id, drug_code, quantity, days) "
            "VALUES (nextval('prescription_id_seq'), %s, %s, %s, %s) RETURNING prescription_id",
            (visit_id, row["drug_code"], row["quantity"], row["days"]),
        ).fetchone()[0])
    return visit_id, prescription_ids


def insert_manual(connection: Any, site: str, visit: dict) -> dict:
    """Thêm bệnh nhân nếu cần, rồi một lượt khám vào đúng trạm cư trú."""
    hospital = connection.execute(
        "SELECT province FROM hospital WHERE hospital_id = %s", (visit["hospital_id"],)
    ).fetchone()
    if hospital is None:
        raise ValueError("Bệnh viện không tồn tại tại trạm đích.")
    patient = visit["patient"]
    if "patient_id" in patient:
        patient_id = patient["patient_id"]
    else:
        patient_id = connection.execute(
            "INSERT INTO patient (patient_id, full_name, birth_year, gender, home_province) "
            "VALUES (nextval('patient_id_seq'), %s, %s, %s, %s) RETURNING patient_id",
            (patient["full_name"], patient["birth_year"], patient["gender"], site),
        ).fetchone()[0]
    visit_id, prescription_ids = insert_visit(
        connection, patient_id, visit["hospital_id"], visit["specialty"],
        visit["visit_date"], visit["result"], visit["prescriptions"],
    )
    cross_region = hospital[0] != site
    return {
        "count": 1, "patient_id": patient_id, "visit_id": visit_id,
        "prescription_ids": prescription_ids, "cross_region": cross_region,
        "message": f"Đã ghi thành công. Bệnh nhân: {'có sẵn' if 'patient_id' in patient else 'mới'}.\n"
                   f"patient_id: {patient_id}\nvisit_id: {visit_id}\n"
                   f"prescription_ids: {prescription_ids}\n"
                   f"Liên vùng: {'Có' if cross_region else 'Không'} "
                   f"(bệnh viện: {PROVINCES.get(hospital[0], hospital[0])}).",
    }


def catalog(connection: Any) -> dict:
    """Đọc danh mục sao chép trực tiếp từ trạm đang chọn, không dùng trạm khác."""
    hospitals = [dict(zip(("hospital_id", "name", "province"), row)) for row in
                 connection.execute("SELECT hospital_id, name, province FROM hospital ORDER BY hospital_id")]
    drugs = [dict(zip(("drug_code", "name", "unit"), row)) for row in
             connection.execute("SELECT drug_code, name, unit FROM drug ORDER BY drug_code")]
    return {"hospitals": hospitals, "drugs": drugs}


def insert_random(connection: Any, site: str, site_no: int, count: int, seed: int) -> dict:
    """Ghi N lượt cho bệnh nhân địa phương, một lần lấy mẫu, một giao dịch."""
    rng = random.Random(seed + site_no)
    connection.execute("SELECT setseed(%s)", ((seed + site_no) % 2147483648 / 1073741824 - 1,))
    patients = connection.execute(
        "SELECT patient_id FROM patient WHERE home_province = %s ORDER BY random() LIMIT %s",
        (site, count),
    ).fetchall()
    if not patients:
        raise ValueError("Trạm chưa có bệnh nhân địa phương; không thể thêm lượt ngẫu nhiên.")
    lookup = catalog(connection)
    hospitals = {province: [row["hospital_id"] for row in lookup["hospitals"]
                            if row["province"] == province] for province in PROVINCES}
    drugs = [row["drug_code"] for row in lookup["drugs"]]
    if not drugs or any(not rows for rows in hospitals.values()):
        raise ValueError("Danh mục thiếu thuốc hoặc bệnh viện của một tỉnh; cần nạp đủ bản sao.")
    cross_count = prescription_count = 0
    start = date(2025, 1, 1)
    span = (date(2026, 6, 30) - start).days
    for index in range(count):
        province = rng.choice([name for name in PROVINCES if name != site]) if rng.random() < 0.07 else site
        specialty = rng.choices(list(SPECIALTIES), (45, 35, 20))[0]
        result = random_result(specialty, rng)
        prescriptions = [
            {"drug_code": rng.choice(drugs), "quantity": rng.randint(1, 60), "days": rng.randint(1, 30)}
            for unused in range(rng.randint(0, 3))
        ]
        insert_visit(connection, patients[index % len(patients)][0], rng.choice(hospitals[province]),
                     specialty, start + timedelta(days=rng.randint(0, span)), result, prescriptions)
        cross_count += province != site
        prescription_count += len(prescriptions)
    return {"count": count, "cross_region_count": cross_count, "prescription_count": prescription_count,
            "seed": seed, "message": f"Đã thêm {count} lượt khám; {cross_count} liên vùng; "
                                     f"{prescription_count} đơn thuốc. Seed: {seed}."}


def run_site(config: dict, site: str, action: Callable[[Any], dict]) -> dict:
    """Mở đúng trạm, commit một lần; lỗi không được định tuyến sang trạm khác."""
    settings = config["sites"][site]
    started = time.perf_counter()
    response = {"site": site, "name": PROVINCES[site], "machine": settings["machine"],
                "address": f"{settings['ip']}:{settings['port']}", "ok": False, "count": 0}
    try:
        import psycopg
    except ImportError:
        response["message"] = "Thiếu psycopg. Chạy bằng ~/cs5104-venv/bin/python. Chưa ghi dữ liệu."
    else:
        connection = None
        committing = False
        try:
            connection = psycopg.connect(
                host=settings["ip"], port=settings["port"], dbname=config["dbname"],
                user="postgres", connect_timeout=3,
            )
            with connection:
                result = action(connection)
                committing = True
            response.update(result, ok=True)
        except (psycopg.Error, ValueError) as error:
            if connection is None:
                explanation = "Không kết nối được trạm đích. Không có dữ liệu nào được ghi."
            elif committing and isinstance(error, psycopg.Error) and not error.sqlstate:
                response["count"] = None
                explanation = ("Mất kết nối khi COMMIT: chưa xác nhận được kết quả. "
                               "Kiểm tra trạm trước khi nhập lại để tránh ghi trùng.")
            else:
                explanation = "Giao dịch đã rollback; không có dòng mới nào được ghi tại trạm này."
            response["message"] = f"{explanation}\nKhông chuyển sang trạm khác.\n\n{error}"
    response["elapsed"] = round(time.perf_counter() - started, 3)
    return response


def allocations(target: str, count: int) -> dict[str, int]:
    """Chia tổng N theo vòng tròn, phần dư ưu tiên thứ tự bốn trạm."""
    sites = list(PROVINCES) if target == "all" else [choice(target, PROVINCES, "Trạm đích")]
    return {site: count // len(sites) + (index < count % len(sites))
            for index, site in enumerate(sites)}


def option(value: Any, label: Any) -> str:
    """Tạo option với giá trị và nhãn đã escape HTML."""
    return f'<option value="{escape(str(value), quote=True)}">{escape(str(label))}</option>'


def number_input(name: str, label: str, low: float, high: float,
                 places: int, default: Any = "", required: bool = True) -> str:
    """Tạo ô số có nhãn, khoảng và bước phù hợp kiểm tra máy chủ."""
    step = 1 if places == 0 else 10 ** -places
    return (f'<label>{escape(label)}<input type="number" name="{escape(name, quote=True)}" '
            f'min="{low}" max="{high}" step="{step}" value="{escape(str(default), quote=True)}" '
            f'{"required" if required else ""}></label>')


def render_page(config: dict, token: str) -> str:
    """Dựng trang tiếng Việt; dữ liệu động luôn được escape trước khi chèn."""
    sites = "".join(option(site, f"{PROVINCES[site]} ({site}) — Máy {settings['machine']} — "
                           f"{settings['ip']}:{settings['port']}")
                    for site, settings in config["sites"].items() if site in PROVINCES)
    sections = []
    for specialty, label in SPECIALTIES.items():
        fields = "".join(number_input(*field) for field in FIELDS[specialty])
        if specialty == "cardio":
            fields += '<label>Nhịp điện tim<select name="ecg_rhythm">' + "".join(
                option(value, value) for value in RHYTHMS) + '</select></label>'
        elif specialty == "eye":
            fields += ('<label>Chẩn đoán (chọn 1–3; giữ Ctrl hoặc Command để chọn nhiều)'
                       '<select name="diagnoses" multiple size="7" required>'
                       + "".join(option(value, value) for value in EYE_DX) + '</select></label>')
        else:
            for index in range(4):
                options = '<option value="">Không chọn</option>' + "".join(
                    f'<option value="{escape(code)}" data-unit="{escape(unit)}" '
                    f'data-low="{low}" data-high="{high}">{escape(code)}</option>'
                    for code, (unit, low, high) in BLOOD_TESTS.items())
                fields += (f'<div class="test row"><label>Xét nghiệm {index + 1}'
                           f'<select name="test_code_{index}">{options}</select></label>'
                           f'<label>Giá trị<input type="number" step="0.01" name="test_value_{index}"></label>'
                           f'<label>Đơn vị<input name="test_unit_{index}" readonly></label></div>')
        sections.append(f'<fieldset data-specialty="{specialty}"><legend>{label}</legend>'
                        f'<div class="grid">{fields}</div></fieldset>')
    prescriptions = "".join(
        f'<div class="row"><label>Mã thuốc {index + 1}<input name="drug_code_{index}" '
        f'list="drugs" maxlength="100"></label>'
        + number_input(f"quantity_{index}", "Số lượng", 1, 60, 0, required=False)
        + number_input(f"days_{index}", "Số ngày", 1, 30, 0, required=False) + '</div>'
        for index in range(3))
    return (PAGE.replace("__SITES__", sites).replace("__FIELDS__", "".join(sections))
            .replace("__PRESCRIPTIONS__", prescriptions).replace("__TOKEN__", escape(token, quote=True))
            .replace("__TODAY__", date.today().isoformat()).replace("__YEAR__", str(date.today().year)))


PAGE = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="csrf-token" content="__TOKEN__"><title>CS5104 — Nhập hồ sơ khám bệnh</title>
<style>
:root{font-family:system-ui,sans-serif;color:#17263a;background:#f2f5f8}*{box-sizing:border-box}
body{max-width:1100px;margin:24px auto;padding:0 18px}h1{font-size:1.65rem}h2{font-size:1.25rem}
form,article{background:white;padding:20px;border:1px solid #cad4df;border-radius:8px;margin:16px 0}
fieldset{border:1px solid #b7c6d7;border-radius:6px;margin:16px 0;padding:16px}legend{font-weight:700}
label{display:flex;flex-direction:column;gap:6px;min-width:0}.grid,.row{display:grid;gap:14px}
.grid{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}.row{grid-template-columns:2fr 1fr 1fr;margin:8px 0}
.test{grid-column:1/-1}input,select,button{font:inherit;padding:9px;border:1px solid #91a2b6;border-radius:4px;min-width:0}
button{background:#154e82;color:white;cursor:pointer;margin-top:12px}button:disabled{opacity:.6;cursor:wait}
:focus-visible{outline:3px solid #ba5700;outline-offset:2px}[hidden]{display:none!important}
.error{color:#8b1414;background:#fff0f0;border:2px solid #b92323;padding:14px}
.success{color:#174b2b;background:#effaf2;border:2px solid #297c44;padding:14px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}small,.hint{color:#405268}
@media(max-width:600px){.row,.grid{grid-template-columns:1fr}}
</style></head><body>
<h1>Nhập hồ sơ khám bệnh liên tỉnh</h1>
<p>Chọn tỉnh cư trú để ghi trực tiếp vào đúng trạm. Bệnh viện ngoài tỉnh là lượt khám <strong>liên vùng</strong>.</p>
<p class="hint">Chỉ dùng trong VPN phòng lab; không có đăng nhập. Không chuyển trạm khi kết nối lỗi.</p>
<noscript>Cần bật JavaScript để nhập hồ sơ và chọn đúng chuyên khoa.</noscript>
<form id="manual"><h2>Thêm bệnh nhân và lượt khám</h2>
<label>Tỉnh cư trú / trạm đích<select name="site" id="site">__SITES__</select></label>
<p id="catalog-status" role="status"></p>
<label>Bệnh nhân<select name="patient_mode" id="patient-mode"><option value="new">Bệnh nhân mới</option>
<option value="existing">Bệnh nhân có sẵn tại trạm này</option></select></label>
<fieldset id="new-patient"><legend>Bệnh nhân mới</legend><div class="grid">
<label>Họ tên<input name="full_name" required maxlength="200" autocomplete="name"></label>
<label>Năm sinh<input type="number" name="birth_year" min="1" max="__YEAR__" value="1990" required></label>
<label>Giới tính<select name="gender"><option value="M">Nam (M)</option><option value="F">Nữ (F)</option></select></label>
</div></fieldset>
<fieldset id="existing-patient" hidden disabled><legend>Bệnh nhân có sẵn</legend>
<label>patient_id tại trạm đích<input type="number" name="patient_id" min="1" max="2147483647" required></label>
<small>Không dò trạm khác. Mã không tồn tại tại trạm đích sẽ bị FK từ chối.</small></fieldset>
<div class="grid"><label>Bệnh viện (đầy đủ các tỉnh)<select name="hospital_id" id="hospital" required></select></label>
<label>Ngày khám<input type="date" name="visit_date" value="__TODAY__" required></label>
<label>Chuyên khoa<select name="specialty" id="specialty"><option value="cardio">Tim mạch</option>
<option value="eye">Mắt</option><option value="blood">Máu</option></select></label></div>
__FIELDS__
<fieldset><legend>Đơn thuốc (không bắt buộc, tối đa 3 dòng)</legend><datalist id="drugs"></datalist>
__PRESCRIPTIONS__</fieldset><button type="submit" id="save" disabled>Ghi vào trạm đích</button></form>
<form id="random"><h2>Thêm ngẫu nhiên N dòng</h2><div class="grid">
<label>Trạm đích<select name="site">__SITES__<option value="all">Cả 4 trạm (chia vòng tròn)</option></select></label>
<label>Số lượt khám N<input type="number" name="count" min="1" max="10000" value="100" required></label>
<label>Seed<input type="number" name="seed" min="0" max="2147483647" value="731905" required></label></div>
<p class="hint">Mỗi dòng là một lượt khám cho bệnh nhân có sẵn; không tạo bệnh nhân mới.
Một giao dịch mỗi trạm; trạm khác vẫn có thể thành công nếu một trạm lỗi.
Ngày ngẫu nhiên trong 2025-01-01–2026-06-30 như bộ sinh. N là tổng số lượt của các trạm.
Nếu N vượt số bệnh nhân tại trạm, mẫu bệnh nhân được dùng lại.</p>
<button type="submit">Thêm ngẫu nhiên N dòng</button></form>
<section id="results" aria-live="polite" aria-atomic="true" tabindex="-1"></section>
<script>
const manual = document.getElementById('manual');
const site = document.getElementById('site');
const save = document.getElementById('save');
const specialty = document.getElementById('specialty');
const results = document.getElementById('results');
const provinceNames = {tayninh:'Tây Ninh',hcm:'TP. Hồ Chí Minh',cantho:'Cần Thơ',dongnai:'Đồng Nai'};
let catalogReady = false;
let busy = false;
function toggleFields() {
  const isNew = document.getElementById('patient-mode').value === 'new';
  for (const [id, visible] of [['new-patient', isNew], ['existing-patient', !isNew]]) {
    const fieldset = document.getElementById(id);
    fieldset.hidden = fieldset.disabled = !visible;
  }
  document.querySelectorAll('[data-specialty]').forEach(fieldset => {
    fieldset.hidden = fieldset.disabled = fieldset.dataset.specialty !== specialty.value;
  });
}
function describe(result) {
  return result.name + ' (' + result.site + ') — Máy ' + result.machine + ' — ' + result.address;
}
function showResults(payload) {
  results.replaceChildren();
  for (const result of payload.results) {
    const article = document.createElement('article');
    article.className = result.ok ? 'success' : 'error';
    const heading = document.createElement('h2');
    heading.textContent = describe(result);
    const message = document.createElement('pre');
    message.textContent = result.message + '\nThời gian: ' + result.elapsed.toFixed(3) + ' s';
    article.append(heading, message);
    results.append(article);
  }
  const summary = document.createElement('p');
  summary.textContent = 'Tổng thời gian: ' + payload.elapsed.toFixed(3) + ' s';
  results.append(summary);
  results.focus();
}
async function loadCatalog() {
  const selected = site.value;
  const status = document.getElementById('catalog-status');
  catalogReady = false;
  save.disabled = true;
  status.className = '';
  status.textContent = 'Đang đọc danh mục tại trạm đích…';
  document.getElementById('hospital').replaceChildren();
  document.getElementById('drugs').replaceChildren();
  try {
    const response = await fetch('/catalog?site=' + encodeURIComponent(selected));
    const data = await response.json();
    if (selected !== site.value) return;
    if (!response.ok || !data.ok) throw new Error(data.message ? describe(data) + '\n' + data.message : 'Không đọc được danh mục.');
    document.getElementById('hospital').replaceChildren(...data.hospitals.map(row =>
      new Option(row.hospital_id + ' — ' + row.name + ' — ' + (provinceNames[row.province] || row.province), row.hospital_id)));
    document.getElementById('drugs').replaceChildren(...data.drugs.map(row =>
      new Option(row.name + ' (' + row.unit + ')', row.drug_code)));
    catalogReady = data.hospitals.length > 0;
    save.disabled = busy || !catalogReady;
    status.textContent = describe(data) + ' · ' + data.hospitals.length + ' bệnh viện · ' + data.drugs.length + ' thuốc';
  } catch (error) {
    if (selected !== site.value) return;
    status.className = 'error';
    status.textContent = error.message;
  }
}
async function submit(event, endpoint) {
  event.preventDefault();
  if (busy) return;
  const fields = new FormData(event.currentTarget);
  const payload = Object.fromEntries(fields);
  if (endpoint === '/visit') {
    payload.diagnoses = fields.getAll('diagnoses');
    payload.tests = Array.from({length:4}, (_, index) => ({code:fields.get('test_code_' + index) || '',
      value:fields.get('test_value_' + index) || '', unit:fields.get('test_unit_' + index) || ''}));
    payload.prescriptions = Array.from({length:3}, (_, index) => ({drug_code:fields.get('drug_code_' + index),
      quantity:fields.get('quantity_' + index), days:fields.get('days_' + index)}));
  }
  busy = true;
  document.querySelectorAll('button[type="submit"]').forEach(button => button.disabled = true);
  results.className = '';
  results.textContent = 'Đang ghi dữ liệu; vui lòng chờ kết quả…';
  try {
    const response = await fetch(endpoint, {method:'POST', headers:{'Content-Type':'application/json',
      'X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content}, body:JSON.stringify(payload)});
    const data = await response.json();
    if (!response.ok) {
      results.className = 'error';
      results.textContent = data.error;
    } else showResults(data);
  } catch (error) {
    results.className = 'error';
    results.textContent = 'Không nhận được kết quả từ giao diện: ' + error.message
      + '. Chưa xác nhận được trạng thái ghi; kiểm tra trước khi gửi lại.';
  } finally {
    busy = false;
    document.querySelectorAll('button[type="submit"]').forEach(button => button.disabled = false);
    save.disabled = !catalogReady;
  }
}
document.getElementById('patient-mode').addEventListener('change', toggleFields);
specialty.addEventListener('change', toggleFields);
site.addEventListener('change', loadCatalog);
manual.addEventListener('submit', event => submit(event, '/visit'));
document.getElementById('random').addEventListener('submit', event => submit(event, '/random'));
document.querySelectorAll('.test').forEach(row => {
  const select = row.querySelector('select');
  select.addEventListener('change', () => {
    const selected = select.selectedOptions[0];
    const value = row.querySelector('input[type="number"]');
    row.querySelector('input[readonly]').value = selected.dataset.unit || '';
    value.value = '';
    value.required = !!select.value;
    value.min = selected.dataset.low || '';
    value.max = selected.dataset.high || '';
  });
});
toggleFields();
loadCatalog();
</script></body></html>
"""


class EntryHandler(BaseHTTPRequestHandler):
    """HTTP cho giao diện lab; JSON POST giới hạn kích thước và có CSRF token."""

    config: dict
    token: str

    def setup(self) -> None:
        """Giới hạn thời gian đọc yêu cầu để tránh kết nối treo vô hạn."""
        self.request.settimeout(15)
        super().setup()

    def reply(self, status: int, body: Any, html: bool = False) -> None:
        """Gửi UTF-8, không cache nội dung hoặc cho phép trình duyệt đoán MIME."""
        content = (body if html else json.dumps(body, ensure_ascii=False, allow_nan=False)).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        """Trả giao diện hoặc danh mục chỉ của trạm được chọn."""
        request = urlsplit(self.path)
        if request.path == "/":
            self.reply(200, render_page(self.config, self.token), html=True)
        elif request.path == "/catalog":
            try:
                query = parse_qs(request.query, max_num_fields=10)
                site = choice(query.get("site", [""])[0], PROVINCES, "Trạm đích")
            except ValueError as error:
                self.reply(400, {"error": str(error)})
                return
            self.reply(200, run_site(self.config, site, catalog))
        else:
            self.reply(404, {"error": "Không tìm thấy đường dẫn."})

    def do_POST(self) -> None:
        """Kiểm tra yêu cầu, ghi từng trạm độc lập, trả kết quả đã commit."""
        if self.path not in ("/visit", "/random"):
            self.reply(404, {"error": "Không tìm thấy đường dẫn."})
            return
        if not secrets.compare_digest(self.headers.get("X-CSRF-Token", "").encode(), self.token.encode()):
            self.reply(403, {"error": "CSRF token không hợp lệ; tải lại giao diện."})
            return
        try:
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Chỉ nhận application/json.")
            length = number(self.headers.get("Content-Length"), "Kích thước yêu cầu", 1, 65536)
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Yêu cầu phải là một đối tượng JSON.")
        except (ValueError, UnicodeError, RecursionError) as error:
            self.reply(400, {"error": f"Yêu cầu không hợp lệ; chưa ghi dữ liệu.\n{error}"})
            return
        try:
            started = time.perf_counter()
            if self.path == "/visit":
                site = choice(data.get("site"), PROVINCES, "Trạm đích")
                visit = parse_visit(data)
                results = [run_site(self.config, site, partial(insert_manual, site=site, visit=visit))]
            else:
                target = choice(data.get("site"), (*PROVINCES, "all"), "Trạm đích")
                count = number(data.get("count"), "Số lượt khám N", 1, 10000)
                seed = number(data.get("seed", 731905), "Seed", 0, 2147483647)
                results = []
                for site, size in allocations(target, count).items():
                    if size:
                        results.append(run_site(self.config, site, partial(
                            insert_random, site=site, site_no=self.config["sites"][site]["site_no"],
                            count=size, seed=seed)))
                    else:
                        settings = self.config["sites"][site]
                        results.append({"site": site, "name": PROVINCES[site], "machine": settings["machine"],
                                        "address": f"{settings['ip']}:{settings['port']}", "ok": True,
                                        "count": 0, "elapsed": 0, "message": "Phân bổ 0 lượt; không kết nối trạm."})
            self.reply(200, {"results": results, "elapsed": round(time.perf_counter() - started, 3)})
        except ValueError as error:
            self.reply(400, {"error": f"Dữ liệu không hợp lệ; chưa ghi dữ liệu.\n{error}"})


def selftest() -> None:
    """Kiểm tra kiểu, khoảng, jsonb ↔ quan hệ và đầu vào lỗi; không cần DB."""
    rng = random.Random(731905)
    for specialty in SPECIALTIES:
        for visit_id in range(1, 101):
            result = random_result(specialty, rng)
            rows = relational_rows(visit_id, specialty, result)
            inputs = dict(result)
            if specialty == "cardio":
                parent, = rows["visit_cardio"]
                restored = dict(zip(("bp_systolic", "bp_diastolic", "heart_rate"), parent[1:4]))
                restored["ecg"] = {"rhythm": parent[4], "qt_ms": parent[5]}
                inputs.update(ecg_rhythm=result["ecg"]["rhythm"], ecg_qt_ms=result["ecg"]["qt_ms"])
            elif specialty == "eye":
                parent, = rows["visit_eye"]
                restored = dict(zip(("va_left", "va_right", "iop_mmhg"), parent[1:]))
                diagnoses = rows["visit_eye_diagnosis"]
                assert [row[1] for row in diagnoses] == list(range(1, len(diagnoses) + 1))
                restored["diagnoses"] = [row[2] for row in diagnoses]
            else:
                parent, = rows["visit_blood"]
                restored = dict(zip(("wbc", "rbc", "glucose"), parent[1:]))
                restored["tests"] = [dict(zip(("code", "value", "unit"), row[1:]))
                                     for row in rows["visit_blood_test"]]
            assert parent[0] == visit_id
            assert all(row[0] == visit_id for group in rows.values() for row in group)
            assert restored == result == json.loads(json.dumps(result))
            assert parse_result(specialty, inputs) == result
            for name, label, low, high, places, default in FIELDS[specialty]:
                value = result["ecg"]["qt_ms"] if name == "ecg_qt_ms" else result[name]
                assert type(value) is (int if places == 0 else float)
            if specialty == "blood":
                assert all(type(row["value"]) is float for row in result["tests"])
    for invalid in ("NaN", "Infinity", "-Infinity", "bad", "", None, True, [], "89", "201", "90.1"):
        try:
            number(invalid, "bp_systolic", 90, 200)
        except ValueError:
            continue
        raise AssertionError(f"Accepted invalid number: {invalid!r}")
    for count in (1, 3, 4, 5, 100, 10000):
        distribution = allocations("all", count)
        assert sum(distribution.values()) == count
        assert max(distribution.values()) - min(distribution.values()) <= 1
    assert option('"<', '<script>') == '<option value="&quot;&lt;">&lt;script&gt;</option>'
    assert random_result("blood", random.Random(731905)) == random_result("blood", random.Random(731905))
    print("PASS: 300 random results; JSON/relational consistency; types/ranges; eye seq=1; validation; allocation; HTML escaping.")


def main() -> None:
    """Chạy kiểm tra độc lập hoặc phục vụ trên máy A, cổng 8080."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return
    with (Path(__file__).resolve().parents[1] / "deploy.toml").open("rb") as stream:
        EntryHandler.config = tomllib.load(stream)
    if set(EntryHandler.config["sites"]) != set(PROVINCES):
        raise ValueError("deploy.toml phải khai báo đúng bốn trạm.")
    EntryHandler.token = secrets.token_urlsafe(32)
    with ThreadingHTTPServer(("0.0.0.0", 8080), EntryHandler) as server:
        print("CS5104 entry: http://192.168.80.201:8080 (0.0.0.0:8080)", flush=True)
        print("Lab VPN only; no authentication. Python 3.12 + psycopg 3.3.6.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Stopped.")


if __name__ == "__main__":
    main()
