#!/usr/bin/env python3
"""
CS5104 — Hệ cơ sở dữ liệu nâng cao · Project nhóm cuối kỳ
Bộ sinh dữ liệu Đề 4: Đăng kiểm phương tiện

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
# Đề 4 — Đăng kiểm phương tiện
# ======================================================================
DE, SEED = 4, 168372
SITES   = ["tayninh", "dongnai", "hcm"]
WEIGHTS = [0.22, 0.30, 0.48]                # tỉ lệ xe theo tỉnh đăng ký
CROSS   = 0.07                              # tỉ lệ lượt kiểm định ở trạm khác tỉnh đăng ký
TYPES, TYPE_MIX = ["truck", "bus", "ev"], [0.45, 0.35, 0.20]
START, END = "2025-01-01", "2026-06-30"
SIZES = {"mini": dict(station=6, defect_code=8, vehicle=12, inspection=36, defect=30),
         "lab":  dict(station=18, defect_code=150, vehicle=25000, inspection=70000, defect=60000)}
PLATE = {"tayninh": "70", "dongnai": "60", "hcm": "51"}
PNAME = {"tayninh": "Tây Ninh", "dongnai": "Đồng Nai", "hcm": "TP. Hồ Chí Minh"}
BRANDS = {"truck": ["Hino","Isuzu","Thaco","Hyundai"], "bus": ["Thaco","Samco","Hyundai"], "ev": ["VinFast","BYD","Tesla"]}
GROUPS = ["Phanh","Lái","Đèn","Khung gầm","Động cơ","Khí thải","Lốp"]

def generate(g, size, w):
    S = SIZES[size]
    per = split_counts(S["station"], WEIGHTS, 2); stations = []; s = 0
    for p, n in zip(SITES, per):
        for j in range(n):
            s += 1; stations.append((s, f"Trạm đăng kiểm {PLATE[p]}-{j+1:02d}D {PNAME[p]}", p))
    w.write("station", ["station_id","name","province"], stations)
    st_by = {p: [x[0] for x in stations if x[2] == p] for p in SITES}
    codes = [(f"D{i:03d}", f"Lỗi {GROUPS[(i-1) % len(GROUPS)].lower()} mức {((i-1)//len(GROUPS))+1}", GROUPS[(i-1) % len(GROUPS)]) for i in range(1, S["defect_code"] + 1)]
    w.write("defect_code", ["defect_code","description","defect_group"], codes)
    zc = Zipf([c[0] for c in codes], 1.1, g)
    vehicles, tr, bu, ev, evc = [], [], [], [], []; tcount = {t: 0 for t in TYPES}
    for i in range(1, S["vehicle"] + 1):
        p = g.wpick(SITES, WEIGHTS); t = g.wpick(TYPES, TYPE_MIX); tcount[t] += 1
        plate = f"{PLATE[p]}{'CDEHK'[i % 5]}-{i:05d}"
        if t == "truck":
            d = {"payload_kg": g.randint(10, 300) * 100, "axles": g.pick([2,2,3,4]), "body": {"type": g.pick(["box","flatbed","tank","dump"]), "length_m": g.uniform(4, 13)}}
            tr.append((i, d["payload_kg"], d["axles"], d["body"]["type"], d["body"]["length_m"]))
        elif t == "bus":
            d = {"seats": g.pick([16, 29, 35, 45]), "standing": g.pick([0, 0, 10, 30]), "doors": g.pick([1, 2, 2, 3])}
            bu.append((i, d["seats"], d["standing"], d["doors"]))
        else:
            ch = g.pick([["AC"], ["AC","DC"], ["AC","DC"]])
            d = {"battery_kwh": g.uniform(30, 120), "range_km": g.randint(200, 600), "charging": ch}
            ev.append((i, d["battery_kwh"], d["range_km"])); evc += [(i, c) for c in ch]
        vehicles.append((i, plate, p, t, g.pick(BRANDS[t]), g.randint(2008, 2026), d))
    w.write("vehicle", ["vehicle_id","plate","reg_province","vehicle_type","brand","year","spec"], vehicles)
    w.write("spec_truck", ["vehicle_id","payload_kg","axles","body_type","body_length_m"], tr)
    w.write("spec_bus", ["vehicle_id","seats","standing","doors"], bu)
    w.write("spec_ev", ["vehicle_id","battery_kwh","range_km"], ev)
    w.write("spec_ev_charging", ["vehicle_id","charging"], evc)
    insp = []; cross = 0
    for i in range(1, S["inspection"] + 1):
        v = vehicles[i - 1] if i <= len(vehicles) else g.pick(vehicles); home = v[2]; p = home
        if g.chance(CROSS):
            p = g.pick([x for x in SITES if x != home]); cross += 1
        d = g.date(START, END); ok = g.chance(0.82)
        insp.append((i, v[0], g.pick(st_by[p]), d, ok, (d.replace(year=d.year + 1) if d.month != 2 or d.day != 29 else d.replace(year=d.year + 1, day=28)) if ok else None))
    w.write("inspection", ["inspection_id","vehicle_id","station_id","inspect_date","passed","valid_until"], insp)
    defects = ((i, g.randint(1, S["inspection"]), zc.pick(), g.wpick(["minor","major","critical"], [60, 30, 10])) for i in range(1, S["defect"] + 1))
    w.write("defect", ["defect_id","inspection_id","defect_code","severity"], defects)
    return {"sites": SITES, "by_region": {"vehicle.reg_province": count_by(vehicles, 2, SITES), "station.province": count_by(stations, 2, SITES)},
            "cross_site": {"definition": "inspection có station.province <> vehicle.reg_province", "rows": cross, "rate": round(cross / S["inspection"], 4)},
            "jsonb_types": {"vehicle.vehicle_type": tcount}}


if __name__ == "__main__":
    main_cli(generate, DE, SEED)
