#!/usr/bin/env python3
"""
CS5104 — Hệ cơ sở dữ liệu nâng cao · Project nhóm cuối kỳ
Bộ sinh dữ liệu Đề 2: Quản lý sinh viên liên cơ sở

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
# Đề 2 — Quản lý sinh viên liên cơ sở
# ======================================================================
DE, SEED = 2, 284617
SITES   = ["campus_a", "campus_b", "campus_c"]
WEIGHTS = [0.50, 0.32, 0.18]                # tỉ lệ sinh viên theo cơ sở theo học
CROSS   = 0.07                              # tỉ lệ lượt đăng ký học ghép ở cơ sở khác
TYPES, TYPE_MIX = ["language", "it", "research"], [0.45, 0.35, 0.20]
START, END = "2025-01-01", "2026-06-30"
SEMESTERS = ["2025-1", "2025-2", "2026-1"]
SIZES = {"mini": dict(course=6, section=18, student=12, enrollment=90, certificate=12),
         "lab":  dict(course=300, section=2500, student=15000, enrollment=120000, certificate=12000)}
MAJORS = ["CNTT","KHMT","HTTT","KTPM","ATTT","KHDL"]
SUBJ = ["Cơ sở dữ liệu","Lập trình Python","Cấu trúc dữ liệu","Mạng máy tính","Hệ điều hành","Học máy","Toán rời rạc","Xác suất thống kê","Kiến trúc máy tính","Công nghệ phần mềm","An toàn thông tin","Trí tuệ nhân tạo"]
IT_CERTS = [("MOS", ["Word","Excel","PowerPoint","Access"]), ("IC3", ["Computing Fundamentals","Key Applications","Living Online"]), ("AWS", ["Cloud Concepts","Security","Technology","Billing"])]
VENUES = ["Hội nghị FAIR","Tạp chí Khoa học ĐH Tân Tạo","Hội nghị KSE","Hội nghị SoICT","Tạp chí Tin học và Điều khiển"]

def generate(g, size, w):
    S = SIZES[size]
    courses = [(f"C{i:03d}", f"{SUBJ[(i-1) % len(SUBJ)]} {((i-1)//len(SUBJ))+1}", g.pick([2,3,3,4])) for i in range(1, S["course"] + 1)]
    w.write("course", ["course_code","name","credits"], courses)
    zc = Zipf([c[0] for c in courses], 0.8, g)
    sections = []
    for i in range(1, S["section"] + 1):
        camp = SITES[(i - 1) % 3] if i <= 3 * len(SEMESTERS) else g.wpick(SITES, WEIGHTS)
        sem = SEMESTERS[((i - 1) // 3) % len(SEMESTERS)] if i <= 3 * len(SEMESTERS) else g.pick(SEMESTERS)
        sections.append((i, zc.pick(), camp, sem, g.person()[0]))
    w.write("section", ["section_id","course_code","campus","semester","lecturer"], sections)
    sec_by = {(c, s): [x[0] for x in sections if x[2] == c and x[3] == s] for c in SITES for s in SEMESTERS}
    students = []
    for i in range(1, S["student"] + 1):
        students.append((i, g.person()[0], g.randint(1998, 2007), g.pick(MAJORS), g.wpick(SITES, WEIGHTS), g.randint(2021, 2025)))
    w.write("student", ["student_id","full_name","birth_year","major_code","home_campus","intake_year"], students)
    enr = []; cross = 0
    for i in range(1, S["enrollment"] + 1):
        st = g.pick(students); sem = g.pick(SEMESTERS); home = st[4]
        camp = home
        if g.chance(CROSS):
            camp = g.pick([c for c in SITES if c != home]); cross += 1
        sid = g.pick(sec_by[(camp, sem)])
        mid = g.gauss(6.5, 1.8, 0, 10, 1); fin = g.gauss(6.3, 2.0, 0, 10, 1)
        enr.append((i, st[0], sid, sem, mid, fin, round(0.3 * mid + 0.7 * fin, 2)))
    w.write("enrollment", ["enrollment_id","student_id","section_id","semester","midterm","final","total"], enr)
    certs, lang, it, itm, res, resco = [], [], [], [], [], []; tcount = {t: 0 for t in TYPES}
    for i in range(1, S["certificate"] + 1):
        st = g.pick(students); t = g.wpick(TYPES, TYPE_MIX); tcount[t] += 1
        if t == "language":
            test = g.pick(["IELTS", "TOEIC"])
            if test == "IELTS":
                sk = {k: g.pick([4.5,5.0,5.5,6.0,6.5,7.0,7.5,8.0]) for k in ["listening","reading","writing","speaking"]}
                ov = round(round(sum(sk.values()) / 4 * 2) / 2, 1)
            else:
                sk = {k: g.randint(10, 99) * 5 for k in ["listening","reading","writing","speaking"]}
                ov = float(sk["listening"] + sk["reading"])
                sk = {k: float(v) for k, v in sk.items()}
            d = {"test": test, "overall": ov, "skills": sk}
            lang.append((i, test, ov, sk["listening"], sk["reading"], sk["writing"], sk["speaking"]))
        elif t == "it":
            nm, mods = g.pick(IT_CERTS); ms = g.sample(mods, g.randint(1, len(mods)))
            d = {"name": nm, "level": g.pick(["core","expert","associate"]), "modules": ms}
            it.append((i, nm, d["level"])); itm += [(i, m) for m in ms]
        else:
            co = [g.person()[0] for _ in range(g.randint(0, 3))]
            d = {"title": f"Nghiên cứu {g.pick(SUBJ).lower()} ứng dụng {g.randint(1,99)}", "venue": g.pick(VENUES),
                 "role": g.pick(["first_author","coauthor"]), "coauthors": co}
            res.append((i, d["title"], d["venue"], d["role"])); resco += [(i, k + 1, n) for k, n in enumerate(co)]
        certs.append((i, st[0], t, g.date(START, END), d))
    w.write("certificate", ["certificate_id","student_id","cert_type","issued_date","detail"], certs)
    w.write("cert_language", ["certificate_id","test","overall","listening","reading","writing","speaking"], lang)
    w.write("cert_it", ["certificate_id","name","level"], it)
    w.write("cert_it_module", ["certificate_id","module"], itm)
    w.write("cert_research", ["certificate_id","title","venue","role"], res)
    w.write("cert_research_coauthor", ["certificate_id","seq","name"], resco)
    return {"sites": SITES, "by_region": {"student.home_campus": count_by(students, 4, SITES), "section.campus": count_by(sections, 2, SITES)},
            "cross_site": {"definition": "enrollment có section.campus <> student.home_campus", "rows": cross, "rate": round(cross / S["enrollment"], 4)},
            "jsonb_types": {"certificate.cert_type": tcount}}


if __name__ == "__main__":
    main_cli(generate, DE, SEED)
