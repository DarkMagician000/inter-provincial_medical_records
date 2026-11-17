#!/usr/bin/env python3
"""
CS5104 — Hệ cơ sở dữ liệu nâng cao · Project nhóm cuối kỳ
Bộ sinh dữ liệu Đề 3: Ngân hàng ba chi nhánh vùng

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
# Đề 3 — Ngân hàng ba chi nhánh vùng
# ======================================================================
DE, SEED = 3, 590243
SITES   = ["hn", "dn", "hcm"]
WEIGHTS = [0.38, 0.17, 0.45]                # tỉ lệ khách hàng theo vùng mở tài khoản
CROSS   = 0.07                              # tỉ lệ giao dịch tại chi nhánh khác vùng của khách
TYPES, TYPE_MIX = ["savings", "mortgage", "auto_loan"], [0.45, 0.35, 0.20]
START, END = "2025-01-01", "2026-06-30"
SIZES = {"mini": dict(branch=6, product=6, customer=12, account=21, transaction=150),
         "lab":  dict(branch=45, product=20, customer=20000, account=35000, transaction=250000)}
REG_NAME = {"hn": "Hà Nội", "dn": "Đà Nẵng", "hcm": "TP. Hồ Chí Minh"}
PROVINCES = [("Đồng Nai", ["Biên Hoà","Long Khánh","Trảng Bom"]), ("TP. Hồ Chí Minh", ["Quận 1","Thủ Đức","Bình Thạnh"]),
             ("Hà Nội", ["Cầu Giấy","Đống Đa","Long Biên"]), ("Đà Nẵng", ["Hải Châu","Sơn Trà"]), ("Tây Ninh", ["Hoà Thành","Trảng Bàng"])]
BRANDS = ["VinFast","Toyota","Hyundai","Kia","Mazda","Honda","Ford"]
PNAME = {"savings": "Tiết kiệm", "mortgage": "Vay thế chấp nhà", "auto_loan": "Vay mua xe"}

def generate(g, size, w):
    S = SIZES[size]
    per = split_counts(S["branch"], WEIGHTS, 2); branches = []; b = 0
    for r, n in zip(SITES, per):
        for j in range(n):
            b += 1; branches.append((b, f"Chi nhánh {REG_NAME[r]} {j+1}", r))
    w.write("branch", ["branch_id","name","region"], branches)
    br_by = {r: [x[0] for x in branches if x[2] == r] for r in SITES}
    zb = {r: Zipf(br_by[r], 1.0, g) for r in SITES}
    products = []
    for i in range(1, S["product"] + 1):
        t = TYPES[(i - 1) % 3]; products.append((f"P{i:02d}", f"{PNAME[t]} {((i-1)//3)+1}", t))
    w.write("product", ["product_code","name","product_type"], products)
    pr_by = {t: [p[0] for p in products if p[2] == t] for t in TYPES}
    customers = [(i, g.person()[0], g.randint(1950, 2005), g.wpick(SITES, WEIGHTS), g.wpick(["mass","affluent","sme"], [70, 20, 10]))
                 for i in range(1, S["customer"] + 1)]
    w.write("customer", ["customer_id","full_name","birth_year","home_region","segment"], customers)
    accounts, sav, mort, auto = [], [], [], []; tcount = {t: 0 for t in TYPES}; acc_home = {}
    for i in range(1, S["account"] + 1):
        c = customers[i - 1] if i <= len(customers) else g.pick(customers)
        t = g.wpick(TYPES, TYPE_MIX); tcount[t] += 1
        if t == "savings":
            d = {"term_months": g.pick([1,3,6,12,24,36]), "rate": g.uniform(2.5, 6.5, 2), "auto_renew": g.chance(0.6)}
            sav.append((i, d["term_months"], d["rate"], d["auto_renew"])); bal = g.randint(10, 5000) * 1_000_000
        elif t == "mortgage":
            pv, dists = g.pick(PROVINCES)
            d = {"property_value": g.randint(8, 120) * 100_000_000, "address": {"province": pv, "district": g.pick(dists)},
                 "term_months": g.pick([120,180,240,300]), "rate": g.uniform(7, 11, 2)}
            mort.append((i, d["property_value"], pv, d["address"]["district"], d["term_months"], d["rate"])); bal = -g.randint(5, 80) * 100_000_000
        else:
            price = g.randint(40, 200) * 10_000_000
            d = {"brand": g.pick(BRANDS), "model_year": g.randint(2018, 2026), "price": price, "down_payment": int(price * g.pick([0.2,0.3,0.4]))}
            auto.append((i, d["brand"], d["model_year"], d["price"], d["down_payment"])); bal = -(price - d["down_payment"])
        accounts.append((i, c[0], g.pick(pr_by[t]), g.date("2018-01-01", END), bal, d)); acc_home[i] = c[3]
    w.write("account", ["account_id","customer_id","product_code","opened_date","balance","detail"], accounts)
    w.write("acc_savings", ["account_id","term_months","rate","auto_renew"], sav)
    w.write("acc_mortgage", ["account_id","property_value","property_province","property_district","term_months","rate"], mort)
    w.write("acc_auto_loan", ["account_id","brand","model_year","price","down_payment"], auto)
    cross = [0]
    def txns():
        for i in range(1, S["transaction"] + 1):
            a = g.randint(1, S["account"]); home = acc_home[a]
            reg = home
            if g.chance(CROSS):
                reg = g.pick([r for r in SITES if r != home]); cross[0] += 1
            yield (i, a, zb[reg].pick(), g.timestamp(START, END), g.randint(1, 2000) * 100_000,
                   g.wpick(["deposit","withdraw","transfer","repay"], [35, 30, 25, 10]))
    w.write("transaction", ["txn_id","account_id","branch_id","txn_time","amount","txn_type"], txns())
    return {"sites": SITES, "by_region": {"customer.home_region": count_by(customers, 3, SITES), "branch.region": count_by(branches, 2, SITES)},
            "cross_site": {"definition": "transaction có branch.region <> customer.home_region", "rows": cross[0], "rate": round(cross[0] / S["transaction"], 4)},
            "jsonb_types": {"product.product_type (theo account)": tcount}}


if __name__ == "__main__":
    main_cli(generate, DE, SEED)
