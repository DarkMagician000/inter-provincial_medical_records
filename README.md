# Hồ sơ khám bệnh liên tỉnh — CSDL phân tán 4 trạm

CS5104 Cơ sở dữ liệu nâng cao — project cuối kỳ, **Đề 1** (seed 731905, k = 4 trạm).
Hệ dựng trên PostgreSQL 18 (Docker), 3 máy LAN. Trạm trung tâm `tayninh` dùng `postgres_fdw` để trả lời Q1–Q5.

Thiết kế chi tiết và lập luận: [`docs/design.html`](docs/design.html). Nhật ký quyết định: [`NOTES.md`](NOTES.md).

## 1. Thiết kế tóm tắt

| Bảng | Cách chia | Ghi chú |
|---|---|---|
| `patient` | ngang chính theo `home_province` | `CHECK (home_province = '<trạm>')` |
| `visit` | ngang dẫn xuất theo `patient` | hồ sơ lưu ở tỉnh cư trú → Q1 chạy trọn 1 trạm |
| `prescription`, `visit_cardio`, `visit_eye`, `visit_blood` | dẫn xuất theo `visit` | |
| `visit_eye_diagnosis`, `visit_blood_test` | dẫn xuất theo `visit_eye` / `visit_blood` | |
| `hospital`, `drug` | sao chép ra cả 4 trạm | nhỏ, gần như chỉ đọc |

- **Khoá chính toàn hệ:** mỗi trạm một dải `site_no·10⁶+1 … site_no·10⁶+999999` (tayninh 1, hcm 2, cantho 3, dongnai 4). Mỗi trạm có sequence cục bộ `patient_id_seq`, `visit_id_seq`, `prescription_id_seq`, và CHECK chặn id ngoài dải.
- **Khoá ngoại:** cả 9 FK đều nằm trong cùng một trạm (FK thật).
- **CHECK jsonb:** `visit_result_ck` kiểm đủ key theo `specialty`.
- **Trạm trung tâm:** 3 foreign server, có `fetch_size 10000` và `async_capable`. Có 8 view `all_<bảng>` (UNION ALL 4 trạm). Q2 và Q5 viết thành 4 nhánh để join và gộp được đẩy xuống từng trạm.

## 2. Triển khai

| Máy | IP | Trạm (cổng) |
|---|---|---|
| A | 192.168.80.201 | `tayninh` trung tâm (5433), `dongnai` (5436), `ref` CSDL đối chứng (5437), giao diện :8080, dashboard :8090 |
| B | 192.168.80.202 | `hcm` (5434) |
| C | 192.168.80.203 | `cantho` (5435) |

Ánh xạ trạm → máy/IP/cổng nằm trong [`deploy.toml`](deploy.toml). Cổng 5432 của máy A để nguyên (máy có sẵn PostgreSQL).

Cấu trúc thư mục:

```
deploy.toml              trạm → máy, IP, cổng
docker-compose.yml       5 dịch vụ PostgreSQL 18 (+iproute2 cho tc netem), profile A/B/C
docker/Dockerfile        postgres:18 + iproute2
Makefile, mk/*.mk        các lệnh make
sql/schema_central.sql   lược đồ tập trung (đúng sơ đồ đề, dùng cho cả ref và 4 trạm)
sql/site_constraints.sql CHECK mảnh, CHECK dải khoá, CHECK jsonb, sequence
sql/link.sql             postgres_fdw + view all_* ở trạm trung tâm
sql/queries/             Q1–Q5 bản phân tán (chạy ở tayninh)
sql/queries_ref/         Q1–Q5 bản tập trung (chạy ở ref)
scripts/load.sh          nạp ref từ CSV, rồi chia mảnh nạp vào 4 trạm
scripts/check.py         make check
scripts/bench.py         make bench → results/
scripts/delay.sh         bật/tắt trễ 30 ms (tc netem trong container tayninh)
scripts/entry.py         giao diện nhập liệu (:8080)
scripts/dashboard.py     dashboard (:8090)
scripts/deploy.sh        đẩy mã từ laptop lên 3 máy (tar | ssh)
results/                 results.csv, EXPLAIN Q1–Q5, số liệu N1/N4/N5
```

## 3. Yêu cầu

- Mỗi máy: Linux, Docker + Docker Compose v2, `make`, `bash`. Người dùng phải thuộc nhóm `docker`.
- Máy A cần thêm: `python3` ≥ 3.11 (bộ sinh dữ liệu), `psql` (client) và `psycopg` 3:
  ```bash
  python3 -m venv ~/cs5104-venv && ~/cs5104-venv/bin/pip install "psycopg[binary]>=3.1"
  ```
  Makefile tự dùng `~/cs5104-venv/bin/python` nếu có.
- `make all` cần máy A SSH được sang B và C bằng khoá, không hỏi mật khẩu.
- Các cổng 5433–5437, 8080, 8090 phải mở trong LAN.

> **Bảo mật:** các container dùng `POSTGRES_HOST_AUTH_METHOD=trust` (khuôn của `cs5104_labs/lan`). Chỉ chạy trong mạng lab, không mở các cổng này ra Internet.

## 4. Dựng lại hệ

### Cách 1 — một lệnh (máy A)

```bash
git clone https://github.com/DarkMagician000/inter-provincial_medical_records.git ~/cs5104_final
cd ~/cs5104_final
make all
```

`make all` làm lần lượt:
1. Đẩy mã sang B, C.
2. Chạy `make up` trên A, B, C.
3. Chạy `data → load → link → check → bench`.

### Cách 2 — từng bước

```bash
# trên máy B:  make up MACHINE=B
# trên máy C:  make up MACHINE=C
# trên máy A:
make up MACHINE=A   # tayninh, dongnai, ref
make data           # chạy bộ sinh: data/lab/*.csv (bỏ qua nếu đã có)
make load           # nạp ref + chia mảnh vào 4 trạm + CHECK/sequence (~15 s)
make link           # postgres_fdw + view all_* ở tayninh
make check          # 3 quy tắc, PK/FK, jsonb ↔ quan hệ, Q1–Q5 = ref
make bench          # đo Q1–Q5 không trễ / trễ 30 ms → results/
make entry          # giao diện nhập liệu  http://192.168.80.201:8080
make dash           # dashboard            http://192.168.80.201:8090
```

Từ laptop Windows (Git Bash) có thể đẩy mã lên cả 3 máy và bật trạm:

```bash
bash scripts/deploy.sh --up
```

### Các lệnh make

| Lệnh | Chạy ở | Việc |
|---|---|---|
| `up MACHINE=A\|B\|C` | máy tương ứng | build image, bật các trạm của máy |
| `data` | A | sinh CSV bằng bộ sinh của giảng viên (không sửa) |
| `load` | A | nạp CSDL đối chứng, chia mảnh, nạp 4 trạm, thêm CHECK + sequence |
| `link` | A | tạo foreign server, schema `hcm/cantho/dongnai`, view `all_*` |
| `check` | A | in PASS/FAIL từng mục; exit ≠ 0 nếu có FAIL |
| `bench` | A | 5 lần/truy vấn, bỏ lần đầu, lấy trung vị → `results/results.csv` + `results/explain/` |
| `delay-on` / `delay-off` | A | thêm/bỏ 30 ms cho gói từ trung tâm tới trạm xa (`tc netem`) |
| `entry` | A | giao diện nhập liệu, cổng 8080 |
| `dash` | A | dashboard, cổng 8090 |
| `site-down SITE=hcm` / `site-up SITE=hcm` | A | tắt/bật container một trạm (qua SSH nếu ở máy khác) — dùng cho D8 |
| `all` | A | dựng toàn bộ từ máy sạch |
| `down MACHINE=A\|B\|C` | máy tương ứng | xoá container **và volume dữ liệu** |

## 5. Kịch bản demo D1–D8

| Mã | Làm | Thấy |
|---|---|---|
| D1 | `make all`, mở dashboard | 4 ô xanh; số dòng mỗi mảnh đúng `results/n1_fragments.csv` |
| D2 | `make check` | toàn PASS: đầy đủ, tái tạo, rời nhau, PK, FK, jsonb ↔ quan hệ |
| D3 | `psql -h 192.168.80.201 -p 5433 -U postgres hospital -f sql/queries/q1.sql` (tương tự q2) | khớp ref; `EXPLAIN` Q1 không có Foreign Scan |
| D4 | Q3 | 1436 lượt; chạm cả 4 trạm vì bệnh nhân tỉnh khác khám ở bệnh viện Tây Ninh nằm ở trạm của tỉnh họ |
| D5 | Q4 (jsonb) và Q5 (`visit_cardio`) | cùng 7516 bệnh nhân |
| D6 | `make delay-on`, chạy lại Q1–Q3, `make delay-off` | Q1 gần như không đổi; Q2, Q3 tăng |
| D7 | Giao diện: 1 dòng vào trạm hcm (máy B), 1 dòng liên vùng, nút "thêm ngẫu nhiên 100 dòng" | dashboard đổi ≤ 2 s; Q3 thấy dòng mới; `make check` vẫn PASS |
| D8 | `make site-down SITE=hcm` … `make site-up SITE=hcm` | ô hcm đỏ rồi xanh; nhập vào hcm báo lỗi, không ghi trạm khác; Q1 vẫn chạy, Q2 lỗi rồi chạy lại |

Đưa dữ liệu về trạng thái gốc sau demo: `make load && make link`.

## 6. Kết quả

Kết quả đo nằm trong [`results/`](results/):

- `results.csv`: Q1–Q5 × trễ 0/30 ms. Gồm trung vị, 5 lần đo, số trạm chạm, số dòng qua mạng.
- `explain/`: EXPLAIN (ANALYZE, VERBOSE) của Q1–Q5.
- `n1_fragments.csv`: số dòng mỗi mảnh.
- `n4_crossregion.csv`: tỉ lệ dòng liên vùng.
- `n5_storage.csv`: dung lượng jsonb so với bản quan hệ, có và không có GIN.

Đáp án đối chứng (CSDL tập trung):
- Q1 = 1464 lượt.
- Q2 tayninh 148.205.540.000 · hcm 155.980.326.500 · cantho 83.289.105.000 · dongnai 51.923.362.500.
- Q3 = 1436 lượt.
- Q4 = Q5 = 7516 bệnh nhân.

## 7. Sử dụng công cụ AI

Theo Mục 8 của đề, nhóm ghi rõ việc dùng AI:

- **Claude (Anthropic, qua Claude Code):** phân tích đề và giáo trình, đề xuất và phản biện thiết kế phân tán, viết `docs/design.html`, `NOTES.md`, README. Claude cũng chia task, review mã và chạy kiểm chứng trên máy thật.
- **Codex (OpenAI):** viết mã theo task trong `NOTES.md`: SQL, Makefile, các script Python/Bash, giao diện, dashboard.

Mọi quyết định thiết kế đều do nhóm thảo luận và chốt; lý do ghi trong `NOTES.md` mục *Decisions*. Mọi số liệu được kiểm lại bằng `make check` trên hệ thật.
