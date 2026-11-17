#!/usr/bin/env python3
"""
CS5104 — Hệ cơ sở dữ liệu nâng cao · Project nhóm cuối kỳ
Bộ sinh dữ liệu Đề 8: Hợp tác xã nông nghiệp

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
# Đề 8 — Hợp tác xã nông nghiệp
# ======================================================================
DE, SEED = 8, 315829
SITES   = ["tayninh", "dongthap", "cantho"]
WEIGHTS = [0.42, 0.30, 0.28]                # tỉ lệ nông hộ theo tỉnh
CROSS   = 0.07                              # tỉ lệ lượt thu hoạch bán cho thương lái tỉnh khác
TYPES, TYPE_MIX = ["rubber", "sugarcane", "rice"], [0.45, 0.35, 0.20]
START, END = "2025-01-01", "2026-06-30"
SIZES = {"mini": dict(crop=6, buyer=6, farm=12, crop_season=40, harvest=150),
         "lab":  dict(crop=12, buyer=300, farm=12000, crop_season=40000, harvest=150000)}
PNAME = {"tayninh": "Tây Ninh", "dongthap": "Đồng Tháp", "cantho": "Cần Thơ"}
CROPS = {"rubber": ["Cao su RRIV 124","Cao su RRIV 209","Cao su PB 260","Cao su GT1"],
         "sugarcane": ["Mía KK3","Mía K95-84","Mía LK92-11","Mía ROC22"],
         "rice": ["Lúa OM18","Lúa ST25","Lúa Đài thơm 8","Lúa OM5451"]}
VARIETY = {"Lúa OM18": "OM18", "Lúa ST25": "ST25", "Lúa Đài thơm 8": "DT8", "Lúa OM5451": "OM5451"}
SEASONS = {"rubber": ["year_round"], "sugarcane": ["year_round"], "rice": ["winter_spring","summer_autumn","autumn_winter"]}
PRICE = {"rubber": (12_000, 18_000), "sugarcane": (1_000, 1_400), "rice": (6_000, 9_000)}

def generate(g, size, w):
    S = SIZES[size]
    crops = []
    for i in range(1, S["crop"] + 1):
        grp = TYPES[(i - 1) % 3]; nm = CROPS[grp][((i - 1) // 3) % 4]; crops.append((f"CR{i:02d}", nm, grp))
    w.write("crop", ["crop_code","name","crop_group"], crops)
    cr_by = {t: [c for c in crops if c[2] == t] for t in TYPES}
    per = split_counts(S["buyer"], WEIGHTS, 2); buyers = []; b = 0
    for p, n in zip(SITES, per):
        for j in range(n):
            b += 1; buyers.append((b, f"Thương lái {g.person()[0]} ({PNAME[p]})", p))
    w.write("buyer", ["buyer_id","name","province"], buyers)
    bu_by = {p: [x[0] for x in buyers if x[2] == p] for p in SITES}
    zb = {p: Zipf(bu_by[p], 1.0, g) for p in SITES}
    farms = [(i, g.person()[0], g.wpick(SITES, WEIGHTS), g.uniform(0.3, 20, 2)) for i in range(1, S["farm"] + 1)]
    w.write("farm", ["farm_id","owner_name","province","area_ha"], farms)
    seasons = []
    for i in range(1, S["crop_season"] + 1):
        f = farms[i - 1] if i <= len(farms) else g.pick(farms); grp = g.wpick(TYPES, TYPE_MIX); c = g.pick(cr_by[grp])
        seasons.append((i, f[0], c[0], g.pick([2025, 2026]), g.pick(SEASONS[grp]), round(max(0.1, f[3] * g.uniform(0.3, 1.0, 2)), 2), grp, f[2]))
    w.write("crop_season", ["season_id","farm_id","crop_code","year","season","area_ha"], [s[:6] for s in seasons])
    harv, mr, ms, mri, mrd = [], [], [], [], []; tcount = {t: 0 for t in TYPES}; cross = 0
    for i in range(1, S["harvest"] + 1):
        s = seasons[i - 1] if i <= len(seasons) else g.pick(seasons); grp = s[6]; home = s[7]; p = home; tcount[grp] += 1
        if g.chance(CROSS):
            p = g.pick([x for x in SITES if x != home]); cross += 1
        if grp == "rubber":
            d = {"drc_percent": g.uniform(25, 40), "latex_liters": g.uniform(50, 2000), "tapping_days": g.randint(5, 25)}
            mr.append((i, d["drc_percent"], d["latex_liters"], d["tapping_days"])); qty = g.uniform(100, 5000)
        elif grp == "sugarcane":
            d = {"ccs": g.uniform(8, 13), "brix": g.uniform(15, 23), "impurity_percent": g.uniform(1, 8)}
            ms.append((i, d["ccs"], d["brix"], d["impurity_percent"])); qty = g.uniform(5000, 120000)
        else:
            dfs = g.sample(["broken","chalky","yellow","immature"], g.randint(0, 2))
            cname = [c[1] for c in crops if c[0] == s[2]][0]
            d = {"moisture_percent": g.uniform(12, 20), "variety": VARIETY[cname], "grade": g.wpick(["A","B","C"], [40, 40, 20]), "defects": dfs}
            mri.append((i, d["moisture_percent"], d["variety"], d["grade"])); mrd += [(i, x) for x in dfs]; qty = g.uniform(1000, 40000)
        lo, hi = PRICE[grp]
        harv.append((i, s[0], g.date(START, END), qty, g.randint(lo // 100, hi // 100) * 100, zb[p].pick(), d))
    w.write("harvest", ["harvest_id","season_id","harvest_date","quantity_kg","price_per_kg","buyer_id","metrics"], harv)
    w.write("metric_rubber", ["harvest_id","drc_percent","latex_liters","tapping_days"], mr)
    w.write("metric_sugarcane", ["harvest_id","ccs","brix","impurity_percent"], ms)
    w.write("metric_rice", ["harvest_id","moisture_percent","variety","grade"], mri)
    w.write("metric_rice_defect", ["harvest_id","defect"], mrd)
    return {"sites": SITES, "by_region": {"farm.province": count_by(farms, 2, SITES), "buyer.province": count_by(buyers, 2, SITES)},
            "cross_site": {"definition": "harvest có buyer.province <> farm.province", "rows": cross, "rate": round(cross / S["harvest"], 4)},
            "jsonb_types": {"crop.crop_group (theo harvest)": tcount}}


if __name__ == "__main__":
    main_cli(generate, DE, SEED)
