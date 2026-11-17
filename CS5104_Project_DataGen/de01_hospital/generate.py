#!/usr/bin/env python3
"""
CS5104 — Hệ cơ sở dữ liệu nâng cao · Project nhóm cuối kỳ
Bộ sinh dữ liệu Đề 1: Hồ sơ khám bệnh liên tỉnh

Cách chạy (Python >= 3.11, chỉ dùng thư viện chuẩn):
    python3 generate.py --size mini     # bộ nhỏ để kiểm tra bằng mắt
    python3 generate.py --size lab      # bộ dùng để đo
Kết quả: output/<size>/<bảng>.csv (mỗi bảng của lược đồ tập trung một tệp) và output/<size>/summary.json.

Seed và tham số đã cố định theo đề — KHÔNG SỬA tệp này. Cùng seed => cùng dữ liệu trên mọi máy.
Cột jsonb được ghi trong CSV dưới dạng chuỗi JSON; nạp bằng COPY ... WITH (FORMAT csv, HEADER true).
"""
# ======================================================================
# Phần dùng chung — KHÔNG SỬA
# ======================================================================
import argparse, csv, json, random, bisect, datetime as dt
from pathlib import Path

HO = ["Nguyễn","Trần","Lê","Phạm","Hoàng","Huỳnh","Phan","Vũ","Võ","Đặng","Bùi","Đỗ","Hồ","Ngô","Dương","Lý","Đinh","Trương","Lâm","Mai"]
HO_W = [38,11,9,7,5,5,4,4,4,3,3,3,2,2,2,1,1,1,1,1]
DEM_NAM = ["Văn","Hữu","Đức","Minh","Quốc","Thanh","Công","Gia","Tuấn","Hoàng"]
DEM_NU = ["Thị","Ngọc","Thu","Thanh","Minh","Bảo","Kim","Mỹ","Phương","Hồng"]
TEN_NAM = ["An","Bình","Cường","Dũng","Đạt","Hải","Hùng","Huy","Khang","Khoa","Long","Lộc","Minh","Nam","Nghĩa","Phát","Phong","Phúc","Quân","Sơn","Tài","Thắng","Thịnh","Toàn","Trí","Trung","Tuấn","Việt","Vinh","Vũ"]
TEN_NU = ["Anh","Chi","Diệp","Dung","Giang","Hà","Hạnh","Hằng","Hiền","Hoa","Hương","Lan","Linh","Loan","Mai","My","Ngân","Ngọc","Nhung","Oanh","Phương","Quyên","Tâm","Thảo","Thư","Trang","Trinh","Uyên","Vân","Yến"]

class Gen:
    def __init__(self, seed):
        self.r = random.Random(seed)
    # ---- ngẫu nhiên cơ bản
    def pick(self, seq): return seq[self.r.randrange(len(seq))]
    def wpick(self, seq, weights): return self.r.choices(seq, weights=weights, k=1)[0]
    def chance(self, p): return self.r.random() < p
    def randint(self, a, b): return self.r.randint(a, b)
    def uniform(self, a, b, nd=1): return round(self.r.uniform(a, b), nd)
    def gauss(self, mu, sd, lo, hi, nd=1):
        x = self.r.gauss(mu, sd); return round(min(hi, max(lo, x)), nd)
    def sample(self, seq, k): return self.r.sample(seq, k)
    # ---- tên người Việt giả lập
    def person(self, gender=None):
        g = gender or self.pick("MF")
        ho = self.wpick(HO, HO_W)
        if g == "M": return f"{ho} {self.pick(DEM_NAM)} {self.pick(TEN_NAM)}", g
        return f"{ho} {self.pick(DEM_NU)} {self.pick(TEN_NU)}", g
    # ---- thời gian
    def date(self, start, end):
        d0 = dt.date.fromisoformat(start); d1 = dt.date.fromisoformat(end)
        return d0 + dt.timedelta(days=self.r.randrange((d1 - d0).days + 1))
    def timestamp(self, start, end):
        d = self.date(start, end)
        return dt.datetime(d.year, d.month, d.day, self.randint(7, 20), self.randint(0, 59), self.randint(0, 59))

class Zipf:
    """Chọn phần tử lệch theo luật Zipf: phần tử đầu danh sách được chọn nhiều nhất."""
    def __init__(self, items, s, gen):
        self.items = list(items); self.g = gen
        acc = 0.0; self.cum = []
        for k in range(1, len(self.items) + 1):
            acc += 1.0 / (k ** s); self.cum.append(acc)
    def pick(self):
        x = self.g.r.random() * self.cum[-1]
        return self.items[bisect.bisect_left(self.cum, x)]

def split_counts(total, weights, at_least=1):
    """Chia total thành các phần theo trọng số, mỗi phần ≥ at_least."""
    n = len(weights); base = [at_least] * n; rest = total - at_least * n
    raw = [rest * w / sum(weights) for w in weights]
    out = [base[i] + int(raw[i]) for i in range(n)]
    i = 0
    while sum(out) < total:
        out[i % n] += 1; i += 1
    return out

class Writer:
    def __init__(self, outdir):
        self.out = Path(outdir); self.out.mkdir(parents=True, exist_ok=True)
        self.counts = {}
    def write(self, table, columns, rows):
        with open(self.out / f"{table}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(columns); n = 0
            for row in rows:
                w.writerow(["" if v is None else (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else
                            ("true" if v is True else "false" if v is False else v)) for v in row]); n += 1
        self.counts[table] = n
    def summary(self, info):
        info["rows"] = self.counts
        with open(self.out / "summary.json", "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)

def count_by(rows, idx, keys):
    d = {k: 0 for k in keys}
    for r in rows: d[r[idx]] += 1
    return d

def main_cli(generate, de, seed):
    ap = argparse.ArgumentParser(description=f"Bộ sinh dữ liệu CS5104 — Đề {de} (seed cố định {seed})")
    ap.add_argument("--size", choices=["mini", "lab"], default="lab")
    ap.add_argument("--out", default=None, help="thư mục kết quả (mặc định output/<size>)")
    a = ap.parse_args()
    out = a.out or str(Path(__file__).resolve().parent / "output" / a.size)
    w = Writer(out); info = generate(Gen(seed), a.size, w)
    info = {"de": de, "seed": seed, "size": a.size, **info}
    w.summary(info)
    print(f"Đề {de} · seed {seed} · cỡ {a.size} → {out}")
    for t, n in w.counts.items(): print(f"  {t:<26}{n:>9}")

# ======================================================================
# Đề 1 — Hồ sơ khám bệnh liên tỉnh
# ======================================================================
DE, SEED = 1, 731905
SITES   = ["tayninh", "hcm", "cantho", "dongnai"]
WEIGHTS = [0.34, 0.36, 0.18, 0.12]          # tỉ lệ bệnh nhân theo tỉnh cư trú
CROSS   = 0.07                              # tỉ lệ lượt khám ở bệnh viện khác tỉnh cư trú
TYPES, TYPE_MIX = ["cardio", "eye", "blood"], [0.45, 0.35, 0.20]
START, END = "2025-01-01", "2026-06-30"
SIZES = {"mini": dict(hospital=8, drug=10, patient=16, visit=60, prescription=150),
         "lab":  dict(hospital=30, drug=500, patient=20000, visit=80000, prescription=200000)}
PROV_NAME = {"tayninh": "Tây Ninh", "hcm": "TP. Hồ Chí Minh", "cantho": "Cần Thơ", "dongnai": "Đồng Nai"}
DRUG_BASE = ["Paracetamol","Amoxicillin","Metformin","Amlodipine","Losartan","Omeprazole","Atorvastatin","Cefuroxime","Vitamin C","Ibuprofen","Salbutamol","Prednisolone"]
UNITS = ["viên","gói","ống","chai","tuýp"]
EYE_DX = ["myopia","hyperopia","astigmatism","cataract","glaucoma","dry_eye","conjunctivitis"]
BLOOD_TESTS = [("ALT","U/L",10,80),("AST","U/L",10,80),("HbA1c","%",4.5,10),("CHOL","mmol/L",3,8),("TG","mmol/L",0.5,4),("CREA","umol/L",50,150)]

def generate(g, size, w):
    S = SIZES[size]
    # bệnh viện
    per = split_counts(S["hospital"], WEIGHTS, 2)
    hospitals = []; hid = 0
    for p, n in zip(SITES, per):
        for j in range(n):
            hid += 1; hospitals.append((hid, f"BV {['Đa khoa','Nhân dân','Quận','Huyện','Mắt','Tim mạch','Nhi','Y học cổ truyền'][j % 8]} {PROV_NAME[p]} {j+1}", p))
    w.write("hospital", ["hospital_id","name","province"], hospitals)
    hosp_by = {p: [h[0] for h in hospitals if h[2] == p] for p in SITES}
    zh = {p: Zipf(hosp_by[p], 1.1, g) for p in SITES}
    # thuốc
    drugs = []
    for i in range(1, S["drug"] + 1):
        drugs.append((f"T{i:04d}", f"{DRUG_BASE[(i-1) % len(DRUG_BASE)]} {g.pick([250,500,5,10,20,40])}mg", g.pick(UNITS), g.randint(2, 400) * 500))
    w.write("drug", ["drug_code","name","unit","price"], drugs)
    zd = Zipf([d[0] for d in drugs], 1.1, g)
    # bệnh nhân
    patients = []
    for i in range(1, S["patient"] + 1):
        name, gen = g.person()
        patients.append((i, name, g.randint(1940, 2020), gen, g.wpick(SITES, WEIGHTS)))
    w.write("patient", ["patient_id","full_name","birth_year","gender","home_province"], patients)
    # lượt khám + bản quan hệ
    visits, cardio, eye, eyedx, blood, btest = [], [], [], [], [], []
    cross = 0; tcount = {t: 0 for t in TYPES}
    for v in range(1, S["visit"] + 1):
        p = g.pick(patients); home = p[4]
        if g.chance(CROSS):
            prov = g.pick([s for s in SITES if s != home]); cross += 1
        else: prov = home
        spec = g.wpick(TYPES, TYPE_MIX); tcount[spec] += 1
        if spec == "cardio":
            r = {"bp_systolic": int(g.gauss(128, 18, 90, 200, 0)), "bp_diastolic": int(g.gauss(80, 10, 50, 120, 0)),
                 "heart_rate": int(g.gauss(76, 12, 45, 140, 0)), "ecg": {"rhythm": g.wpick(["sinus","afib","brady","tachy"], [80,6,7,7]), "qt_ms": g.randint(340, 480)}}
            cardio.append((v, r["bp_systolic"], r["bp_diastolic"], r["heart_rate"], r["ecg"]["rhythm"], r["ecg"]["qt_ms"]))
        elif spec == "eye":
            dx = g.sample(EYE_DX, g.randint(1, 3))
            r = {"va_left": g.uniform(1, 10), "va_right": g.uniform(1, 10), "iop_mmhg": g.randint(10, 30), "diagnoses": dx}
            eye.append((v, r["va_left"], r["va_right"], r["iop_mmhg"]))
            eyedx += [(v, k + 1, d) for k, d in enumerate(dx)]
        else:
            tests = []
            for code, unit, lo, hi in g.sample(BLOOD_TESTS, g.randint(1, 4)):
                tests.append({"code": code, "value": g.uniform(lo, hi, 2), "unit": unit})
            r = {"wbc": g.uniform(3.5, 12, 2), "rbc": g.uniform(3.5, 6, 2), "glucose": g.uniform(3.8, 12, 2), "tests": tests}
            blood.append((v, r["wbc"], r["rbc"], r["glucose"]))
            btest += [(v, t["code"], t["value"], t["unit"]) for t in tests]
        visits.append((v, p[0], zh[prov].pick(), spec, g.date(START, END), r))
    w.write("visit", ["visit_id","patient_id","hospital_id","specialty","visit_date","result"], visits)
    w.write("visit_cardio", ["visit_id","bp_systolic","bp_diastolic","heart_rate","ecg_rhythm","ecg_qt_ms"], cardio)
    w.write("visit_eye", ["visit_id","va_left","va_right","iop_mmhg"], eye)
    w.write("visit_eye_diagnosis", ["visit_id","seq","diagnosis"], eyedx)
    w.write("visit_blood", ["visit_id","wbc","rbc","glucose"], blood)
    w.write("visit_blood_test", ["visit_id","code","value","unit"], btest)
    # đơn thuốc
    presc = ((i, g.randint(1, S["visit"]), zd.pick(), g.randint(1, 60), g.randint(1, 30)) for i in range(1, S["prescription"] + 1))
    w.write("prescription", ["prescription_id","visit_id","drug_code","quantity","days"], presc)
    return {"sites": SITES, "by_region": {"patient.home_province": count_by(patients, 4, SITES), "hospital.province": count_by(hospitals, 2, SITES)},
            "cross_site": {"definition": "visit có hospital.province <> patient.home_province", "rows": cross, "rate": round(cross / S["visit"], 4)},
            "jsonb_types": {"visit.specialty": tcount}}


if __name__ == "__main__":
    main_cli(generate, DE, SEED)
