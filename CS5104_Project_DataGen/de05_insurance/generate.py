#!/usr/bin/env python3
"""
CS5104 — Hệ cơ sở dữ liệu nâng cao · Project nhóm cuối kỳ
Bộ sinh dữ liệu Đề 5: Bảo hiểm ba văn phòng vùng

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
# Đề 5 — Bảo hiểm ba văn phòng vùng
# ======================================================================
DE, SEED = 5, 846051
SITES   = ["north", "central", "south"]
WEIGHTS = [0.40, 0.17, 0.43]                # tỉ lệ người được bảo hiểm theo vùng cấp hợp đồng
CROSS   = 0.07                              # tỉ lệ hồ sơ bồi thường nộp ở văn phòng khác vùng
TYPES, TYPE_MIX = ["motor", "health", "property"], [0.45, 0.35, 0.20]
START, END = "2025-01-01", "2026-06-30"
SIZES = {"mini": dict(plan=6, office=6, policyholder=12, policy=24, claim=36),
         "lab":  dict(plan=25, office=30, policyholder=20000, policy=40000, claim=60000)}
RNAME = {"north": "Miền Bắc", "central": "Miền Trung", "south": "Miền Nam"}
LNAME = {"motor": "Bảo hiểm xe", "health": "Bảo hiểm sức khoẻ", "property": "Bảo hiểm nhà"}
PARTS = ["bumper","headlight","door","mirror","windshield","hood","fender","tail_light"]
ITEMS = [("BED", 500_000, 3_000_000), ("DRUG", 200_000, 20_000_000), ("SURG", 5_000_000, 80_000_000), ("LAB", 300_000, 5_000_000), ("IMG", 500_000, 8_000_000)]
HOSP = ["BV Đa khoa Tây Ninh","BV Chợ Rẫy","BV Bạch Mai","BV Đà Nẵng","BV Từ Dũ","BV Hoàn Mỹ"]

def generate(g, size, w):
    S = SIZES[size]
    plans = [(f"PL{i:02d}", f"{LNAME[TYPES[(i-1) % 3]]} gói {((i-1)//3)+1}", TYPES[(i-1) % 3]) for i in range(1, S["plan"] + 1)]
    w.write("plan", ["plan_code","name","line"], plans)
    pl_by = {t: [p[0] for p in plans if p[2] == t] for t in TYPES}
    line_of = {p[0]: p[2] for p in plans}
    per = split_counts(S["office"], WEIGHTS, 2); offices = []; o = 0
    for r, n in zip(SITES, per):
        for j in range(n):
            o += 1; offices.append((o, f"Văn phòng {RNAME[r]} {j+1}", r))
    w.write("office", ["office_id","name","region"], offices)
    of_by = {r: [x[0] for x in offices if x[2] == r] for r in SITES}
    holders = [(i, g.person()[0], g.randint(1950, 2006), g.wpick(SITES, WEIGHTS)) for i in range(1, S["policyholder"] + 1)]
    w.write("policyholder", ["holder_id","full_name","birth_year","home_region"], holders)
    policies = []
    for i in range(1, S["policy"] + 1):
        h = holders[i - 1] if i <= len(holders) else g.pick(holders)
        t = g.wpick(TYPES, TYPE_MIX); s = g.date("2024-01-01", "2026-03-31")
        policies.append((i, h[0], g.pick(pl_by[t]), s, s.replace(year=s.year + 1) if not (s.month == 2 and s.day == 29) else s.replace(year=s.year + 1, day=28), g.randint(10, 300) * 100_000))
    w.write("policy", ["policy_id","holder_id","plan_code","start_date","end_date","premium"], policies)
    home_of = {h[0]: h[3] for h in holders}
    claims, mo, mop, he, hei, pr = [], [], [], [], [], []; tcount = {t: 0 for t in TYPES}; cross = 0
    for i in range(1, S["claim"] + 1):
        p = g.pick(policies); t = line_of[p[2]]; tcount[t] += 1; home = home_of[p[1]]; r = home
        if g.chance(CROSS):
            r = g.pick([x for x in SITES if x != home]); cross += 1
        if t == "motor":
            parts = g.sample(PARTS, g.randint(1, 4))
            d = {"plate": f"{g.pick(['29A','43A','51F','70A','60A'])}-{g.randint(100,999)}.{g.randint(10,99)}", "damage_level": g.pick(["light","medium","heavy"]),
                 "parts": parts, "garage": f"Gara {g.pick(['Hoà Thành','Thành Công','Phú Mỹ','An Phát','Đông Á'])}"}
            mo.append((i, d["plate"], d["damage_level"], d["garage"])); mop += [(i, x) for x in parts]
            amount = g.randint(2, 150) * 1_000_000
        elif t == "health":
            items = [{"code": c, "cost": g.randint(lo // 100_000, hi // 100_000) * 100_000} for c, lo, hi in g.sample(ITEMS, g.randint(1, 4))]
            d = {"hospital": g.pick(HOSP), "days_inpatient": g.wpick([0,1,2,3,5,7,10,14], [20,15,15,15,12,10,8,5]), "items": items}
            he.append((i, d["hospital"], d["days_inpatient"])); hei += [(i, x["code"], x["cost"]) for x in items]
            amount = sum(x["cost"] for x in items)
        else:
            d = {"damaged_area_m2": g.uniform(2, 120), "cause": g.pick(["flood","fire","storm","theft"]), "photos_count": g.randint(1, 30)}
            pr.append((i, d["damaged_area_m2"], d["cause"], d["photos_count"])); amount = g.randint(5, 500) * 1_000_000
        claims.append((i, p[0], g.pick(of_by[r]), g.date(START, END), t, amount, g.wpick(["pending","approved","rejected"], [15, 70, 15]), d))
    w.write("claim", ["claim_id","policy_id","office_id","claim_date","claim_type","amount","status","detail"], claims)
    w.write("claim_motor", ["claim_id","plate","damage_level","garage"], mo)
    w.write("claim_motor_part", ["claim_id","part"], mop)
    w.write("claim_health", ["claim_id","hospital","days_inpatient"], he)
    w.write("claim_health_item", ["claim_id","code","cost"], hei)
    w.write("claim_property", ["claim_id","damaged_area_m2","cause","photos_count"], pr)
    return {"sites": SITES, "by_region": {"policyholder.home_region": count_by(holders, 3, SITES), "office.region": count_by(offices, 2, SITES)},
            "cross_site": {"definition": "claim có office.region <> policyholder.home_region", "rows": cross, "rate": round(cross / S["claim"], 4)},
            "jsonb_types": {"claim.claim_type": tcount}}


if __name__ == "__main__":
    main_cli(generate, DE, SEED)
