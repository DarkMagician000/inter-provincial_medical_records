#!/usr/bin/env python3
"""
CS5104 — Hệ cơ sở dữ liệu nâng cao · Project nhóm cuối kỳ
Bộ sinh dữ liệu Đề 7: Vận chuyển hàng hoá bốn vùng

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
# Đề 7 — Vận chuyển hàng hoá bốn vùng
# ======================================================================
DE, SEED = 7, 957164
SITES   = ["north", "central", "south", "mekong"]
WEIGHTS = [0.35, 0.15, 0.38, 0.12]          # tỉ lệ đơn theo vùng gửi
CROSS   = 0.07                              # tỉ lệ đơn gửi liên vùng
TYPES, TYPE_MIX = ["frozen", "fragile", "bulky"], [0.45, 0.35, 0.20]
START, END = "2025-01-01", "2026-06-30"
SIZES = {"mini": dict(hub=8, carrier=4, shipment=16, parcel=24),
         "lab":  dict(hub=40, carrier=15, shipment=30000, parcel=45000)}
RNAME = {"north": "Miền Bắc", "central": "Miền Trung", "south": "Miền Nam", "mekong": "ĐBSCL"}
CITY = {"north": ["Hà Nội","Hải Phòng","Bắc Ninh"], "central": ["Đà Nẵng","Huế","Quy Nhơn"], "south": ["TP.HCM","Bình Dương","Tây Ninh"], "mekong": ["Cần Thơ","Cà Mau","Vĩnh Long"]}
HANDLING = ["this_side_up","no_stack","keep_dry","handle_with_care"]

def generate(g, size, w):
    S = SIZES[size]
    per = split_counts(S["hub"], WEIGHTS, 2); hubs = []; h = 0
    for r, n in zip(SITES, per):
        for j in range(n):
            h += 1; hubs.append((h, f"Kho {CITY[r][j % 3]} {j+1}", r))
    w.write("hub", ["hub_id","name","region"], hubs)
    hub_by = {r: [x[0] for x in hubs if x[2] == r] for r in SITES}
    zh = {r: Zipf(hub_by[r], 1.0, g) for r in SITES}
    carriers = [(i, f"Hãng xe {g.pick(['Phương Trang','Thành Bưởi','Kim Long','Mai Linh','Hoàng Long','Sao Việt'])} {i}", ["motorbike","van","truck","reefer"][(i-1) % 4]) for i in range(1, S["carrier"] + 1)]
    w.write("carrier", ["carrier_id","name","vehicle_type"], carriers)
    ships = []; cross = 0
    for i in range(1, S["shipment"] + 1):
        o = g.wpick(SITES, WEIGHTS); d = o
        if g.chance(CROSS):
            d = g.pick([x for x in SITES if x != o]); cross += 1
        ships.append((i, g.person()[0], o, d, g.randint(1, S["carrier"]), g.timestamp(START, END), g.randint(15, 600) * 1000))
    w.write("shipment", ["shipment_id","sender_name","origin_region","dest_region","carrier_id","created_at","fee"], ships)
    parcels, fz, fr, frh, bk = [], [], [], [], []; tcount = {t: 0 for t in TYPES}
    for i in range(1, S["parcel"] + 1):
        sid = i if i <= S["shipment"] else g.randint(1, S["shipment"])
        t = g.wpick(TYPES, TYPE_MIX); tcount[t] += 1
        if t == "frozen":
            lo = g.pick([-30, -25, -20, -18, 0, 2]); d = {"temp_min_c": lo, "temp_max_c": lo + g.pick([2, 5, 7]), "max_hours": g.pick([12, 18, 24, 36, 48])}
            fz.append((i, d["temp_min_c"], d["temp_max_c"], d["max_hours"]))
        elif t == "fragile":
            hd = g.sample(HANDLING, g.randint(1, 3)); d = {"packing_level": g.randint(1, 3), "insured_value": g.randint(1, 100) * 500_000, "handling": hd}
            fr.append((i, d["packing_level"], d["insured_value"])); frh += [(i, x) for x in hd]
        else:
            dims = {"l": g.randint(80, 300), "w": g.randint(50, 200), "h": g.randint(50, 220)}; d = {"dims_cm": dims, "needs_forklift": g.chance(0.4)}
            bk.append((i, dims["l"], dims["w"], dims["h"], d["needs_forklift"]))
        parcels.append((i, sid, t, g.uniform(0.5, 500, 2), d))
    w.write("parcel", ["parcel_id","shipment_id","goods_type","weight_kg","attrs"], parcels)
    w.write("parcel_frozen", ["parcel_id","temp_min_c","temp_max_c","max_hours"], fz)
    w.write("parcel_fragile", ["parcel_id","packing_level","insured_value"], fr)
    w.write("parcel_fragile_handling", ["parcel_id","handling"], frh)
    w.write("parcel_bulky", ["parcel_id","len_cm","width_cm","height_cm","needs_forklift"], bk)
    import datetime as _dt
    def events():
        eid = 0
        for s in ships:
            sid, _, o, d, _, t0, _ = s
            ho = zh[o].pick(); hd = zh[d].pick() if d != o else ho
            seq = [("created", ho), ("in_hub", ho), ("departed", ho)]
            if d != o: seq += [("in_hub", hd)]
            seq += [("out_for_delivery", hd), ("delivered", hd)]
            if g.chance(0.08): seq = seq[:g.randint(1, len(seq) - 1)]      # đơn chưa giao xong
            t = t0
            for st, hub in seq:
                eid += 1; yield (eid, sid, hub, t, st)
                t = t + _dt.timedelta(hours=g.randint(2, 30))
    w.write("tracking_event", ["event_id","shipment_id","hub_id","event_time","status"], events())
    return {"sites": SITES, "by_region": {"shipment.origin_region": count_by(ships, 2, SITES), "hub.region": count_by(hubs, 2, SITES)},
            "cross_site": {"definition": "shipment có dest_region <> origin_region", "rows": cross, "rate": round(cross / S["shipment"], 4)},
            "jsonb_types": {"parcel.goods_type": tcount}}


if __name__ == "__main__":
    main_cli(generate, DE, SEED)
