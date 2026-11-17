# Context

CS5104 project cuối kỳ — **Đề 1: Hồ sơ khám bệnh liên tỉnh**, k = 4 trạm, seed 731905.
Nguồn: `project1.pdf` trang 1–8; bộ sinh `CS5104_Project_DataGen/de01_hospital/generate.py` (không sửa).

## Yêu cầu cốt lõi
- Tự đề xuất phân tán lược đồ tập trung ra 4 trạm PostgreSQL 18, ≥ 2 máy LAN. Máy A: trạm trung tâm (tayninh) + giao diện + dashboard. Máy B: ≥ 1 trạm.
- Trạm trung tâm dùng `postgres_fdw`, tạo view `all_<bảng>` cho mỗi bảng bị chia.
- Ràng buộc bắt buộc: dữ liệu ở đúng vùng; đầy đủ/tái tạo/rời nhau; **Q1 chạy trọn tại một trạm (EXPLAIN không có Foreign Scan)**; Q1–Q5 tại trung tâm khớp CSDL đối chứng; PK/FK giữ được hoặc kiểm tra bằng truy vấn; **không thêm/bớt/đổi tên bảng, cột** (chỉ thêm index, CHECK, view).
- Lệnh make: `up MACHINE=A|B · data · load · link · check · bench · delay-on/delay-off (30 ms) · entry · dash · all · down`.
- Giao diện nhập liệu: ghi thẳng vào trạm đích, jsonb + bản quan hệ trong **một giao dịch**, báo trạm/máy, báo lỗi khi trạm chết (không ghi nhầm trạm khác), nút thêm ngẫu nhiên N dòng.
- Dashboard: mỗi trạm một ô (máy, IP, xanh/đỏ, số dòng từng bảng, đọc thẳng trạm), so với đối chứng, nhật ký sự kiện, refresh ≤ 2 s.
- Demo D1–D8; giải thích N1–N5. Đo mỗi truy vấn 5 lần, bỏ lần đầu, lấy trung vị → `results/results.csv` + EXPLAIN Q1–Q5.
- Chấm: M1 thiết kế 1,5 · M2 hệ chạy D1–D8 3,5 (chỉ 1 máy: tối đa 1,75) · M3 số liệu/báo cáo/slide 2,5 · M4 vấn đáp 2,5. Báo cáo PDF ≤ 10 trang; GitHub tag `final`.

## Lược đồ
hospital, drug, patient(home_province), visit(patient_id, hospital_id, specialty, visit_date, result jsonb), prescription(visit_id, drug_code); bản quan hệ của jsonb: visit_cardio, visit_eye, visit_eye_diagnosis(visit_id, seq), visit_blood, visit_blood_test(visit_id, code).

## Truy vấn
- Q1: số lượt khám theo chuyên khoa của **bệnh nhân Tây Ninh**, 3/2026 — chỉ trạm tayninh.
- Q2: tổng tiền thuốc theo tỉnh cư trú, năm 2025 — gộp 4 trạm.
- Q3: lượt khám **tại bệnh viện ở Tây Ninh**, 3/2026, gồm bệnh nhân tỉnh khác — liên vùng.
- Q4: bệnh nhân có ≥ 1 lượt cardio với bp_systolic ≥ 140, đọc jsonb. Q5: như Q4, đọc visit_cardio.

## Số liệu thực đo từ bộ sinh (lab, 2026-11-16)
| | tayninh | hcm | cantho | dongnai | tổng |
|---|---|---|---|---|---|
| patient (home_province) | 6819 | 7172 | 3683 | 2326 | 20000 |
| hospital (province) | 10 | 10 | 6 | 4 | 30 |
| visit theo tỉnh bệnh nhân | 26907 | 28697 | 14936 | 9460 | 80000 |
| visit theo tỉnh bệnh viện | 26248 | 27810 | 15407 | 10535 | 80000 |
| prescription theo tỉnh bệnh viện | 65606 | 69403 | 38560 | 26431 | 200000 |

- Liên vùng: 5724 visit (7,16%); 4964 bệnh nhân có ít nhất 1 lượt khám ngoài tỉnh.
- jsonb: cardio 35943, eye 28068, blood 15989. eye_diagnosis 56118, blood_test 40237.
- Q1 tham chiếu: 1464 lượt. Q3 tham chiếu: 1436 lượt (1359 bệnh nhân Tây Ninh + 77 tỉnh khác: hcm 43, cantho 17, dongnai 17).
- 6456 visit không có đơn thuốc; 375 bệnh nhân không có lượt khám. prescription.visit_id chọn ngẫu nhiên đều trên toàn bộ visit (không theo bệnh nhân).
- Bộ sinh trên Windows lỗi `UnicodeEncodeError` (cp1252) khi in — phải chạy với `PYTHONUTF8=1`. Windows có thể không có `python3` → Makefile cần xử lý.

## Tài liệu môn học (đọc 2026-11-16) — điểm áp dụng cho project
Giáo trình CS5104 (224 tr., Đ.H. Tân Tạo; dựa Özsu & Valduriez 2020). Tập 2 (PDF) không có trong thư mục; gói cs5104_labs có ở `E:\MCS\CS5104\labs` (xem mục dưới).
- §2.2 Mã 2.1: kiểm 3 quy tắc bằng SQL — đầy đủ (NOT EXISTS), tái tạo (EXCEPT ALL hai chiều), rời nhau (GROUP BY id HAVING count>1). Luôn UNION ALL/EXCEPT ALL. Bản sao của bảng chép không vi phạm rời nhau. → khuôn cho `make check`.
- §2.4: dẫn xuất = semijoin (`WHERE EXISTS`); một bảng chỉ dẫn xuất theo 1 owner, chọn owner có phép kết nối dùng nhiều nhất. Ví dụ 2.3 (orders theo customer vs theo store) giống hệt visit theo patient vs hospital → trích dẫn khi lập luận. FK là điều kiện bắt buộc để dẫn xuất thoả 3 quy tắc.
- §2.7: 3 quy tắc cấp phát: đặt mảnh tại nơi dùng chủ yếu; mảnh nhỏ-đọc nhiều-ít ghi thì sao chép mọi trạm; mảnh ghi nhiều hạn chế bản. Ví dụ 2.5 (product) → khuôn lập luận sao chép hospital/drug.
- §2.11 Bảng 2.5 + lưu ý: mảnh tạo bằng CREATE TABLE (LIKE) — giáo trình KHÔNG khai báo FK giữa mảnh, kiểm bằng 3 quy tắc. Ta làm chặt hơn: FK cục bộ thật.
- §2.9 (Citus): PK trên bảng phân tán phải chứa cột phân mảnh vì "mỗi worker chỉ kiểm tra được tính duy nhất trong phần dữ liệu của mình" → đúng vấn đề PK toàn hệ. Giáo trình KHÔNG có cơ chế sinh id cho postgres_fdw thủ công (không có sequence/dải/INCREMENT) → phần này nhóm tự đề xuất, đó là lý do đề hỏi.
- §1.4.2 Bảng 1.2: postgres_fdw tốn ~5 vòng khứ hồi/truy vấn (START TRANSACTION, DECLARE CURSOR, FETCH, CLOSE, COMMIT); fetch_size mặc định 100 → mỗi 100 dòng thêm 1 vòng. → công thức giải thích N3.
- §3.4.4: fetch_size (giảm số vòng) và async_capable (hỏi song song các trạm qua UNION ALL). §3.6 cấu hình chuẩn: `ALTER SERVER ... OPTIONS (ADD fetch_size '10000', ADD async_capable 'true')`. Gộp 2 giai đoạn (Mã 3.2): mỗi trạm gộp trước. Semijoin `= ANY(ARRAY(...))` (Mã 3.3).
- §3.5: postgres_fdw chỉ đẩy xuống hàm/toán tử built-in → không dùng hàm tự viết trong WHERE của Q2/Q3.
- §1.6: trễ giả lập bằng `tc netem`; nếu thiếu netem dùng `common/latency_proxy.py` (trong cs5104_labs). Trạm hỏng = dừng container.

## Gói lab của thầy `E:\MCS\CS5104\labs` (đọc 2026-11-16) — tiền lệ + code tái dùng
- **Tiền lệ khoá cho dòng mới (lab07_security_pitr/sql/pitr_prepare.sql):** `CREATE SEQUENCE new_order_id START 1000001;` vì "đơn cũ của STR-lab có mã tới 100000"; insert bằng `nextval('new_order_id')`; dashboard nhận diện dòng mới bằng dải `order_id >= 1000001`. Một trạm, nhưng đúng ý tưởng "dải tách khỏi dữ liệu gốc" → mở rộng thành mỗi trạm một dải.
- Không bài nào có insert đa trạm vào bảng phân mảnh. lab05 (replication) dùng BIGSERIAL vì chỉ ghi ở nút chủ. lab02 b5 (Citus) chỉ minh hoạ khoá phân mảnh tồi.
- lab02 a1_site_setup.sql: mảnh tạo bằng `CREATE TABLE (LIKE src.x)` + chỉ PRIMARY KEY, không FK; dẫn xuất bằng `WHERE ... IN (SELECT ... FROM mảnh_cha)`; region/product chép. Đặt tên `customer_hn` — **ta không được đổi tên bảng** → mỗi trạm giữ tên gốc.
- Tái dùng: a4_check_rules.sql (khuôn `make check`), a3_source_link.sql + lab03 link.sql (CREATE SERVER với fetch_size/async_capable, IMPORT FOREIGN SCHEMA LIMIT TO), a6/a7 (cố ý phá/khôi phục quy tắc — dùng cho demo), lan/docker-compose.yml + lab01 Dockerfile (postgres:18 + iproute2, NET_ADMIN, listen_addresses=*, PG_PORT), lab03 scripts/netem.sh (delay on/off trong container, ms=0 xoá qdisc), common/dashboard/dashboard.py (stdlib http.server, kiểm `wrong_customer`/`orphan_orders`), common/latency_proxy.py (dự phòng).

# Decisions
## Đã chốt
- [2026-11-16] Không chia dọc — 4 vùng đồng nhất (cùng nghiệp vụ, specialty 45/35/20 như nhau mọi tỉnh, generate.py:155); không nhóm cột nào thuộc riêng vùng; chia dọc làm Q1 phải join mảnh. jsonb ↔ 5 bản quan hệ là 2 cách lưu do đề cho, không phải mảnh dọc.
- [2026-11-16] patient: ngang chính theo home_province (4 mảnh: 6819/7172/3683/2326).
- [2026-11-16] visit: ngang dẫn xuất theo patient (qua patient_id) — Q1 chạy trọn 1 trạm; khớp bối cảnh "hồ sơ tại tỉnh cư trú". Hệ quả: 5724 visit (7,16%) liên vùng, Q3 phải hỏi 4 trạm.
- [2026-11-16] prescription, visit_cardio, visit_eye, visit_blood: dẫn xuất theo visit; visit_eye_diagnosis theo visit_eye; visit_blood_test theo visit_blood → mọi FK con-cha cục bộ.
- [2026-11-16] hospital, drug: sao chép toàn bộ ra 4 trạm (30 + 500 dòng, gần như chỉ đọc) → FK visit.hospital_id, prescription.drug_code cục bộ kể cả lượt liên vùng; Q2 tính giá, Q3 lọc province đẩy xuống từng trạm. Nhược: thêm hospital/drug phải ghi 4 trạm (giao diện không yêu cầu).
  Số liệu lập luận: mỗi trạm tham chiếu đủ 30/30 bệnh viện (chia hospital không giảm được gì trạm cần). Sao chép tốn thêm 1590 dòng = 0,33% tổng 476.885. Q3 nếu sao chép: hcm/cantho/dongnai trả về 43/17/17 dòng; nếu chia hospital: phải kéo toàn bộ visit 3/2026 của 3 trạm xa = 1636/811/549 dòng, với fetch_size mặc định 100 của postgres_fdw ≈ 17/9/6 lần FETCH (mỗi lần 1 vòng khứ hồi) thay vì 1.
- [2026-11-16] Cấp phát: cs-a 192.168.80.201 (labsoe) = tayninh (trung tâm) + dongnai + giao diện + dashboard + CSDL đối chứng; cs-b .202 (labsoe) = hcm; cs-c .203 (labsit06) = cantho. Dòng/máy 217.708 / 171.493 / 89.274. Lý do: tayninh bắt buộc ở máy A; dongnai (nhỏ nhất) cùng máy trung tâm tạo cặp so N3 cùng máy vs qua LAN; B, C mỗi máy 1 trạm để D8 tắt gọn. Trạm chạy Docker PostgreSQL 18, cổng 5433–5436 (5432 trên .201 đã bị PostgreSQL có sẵn chiếm).
- [2026-11-16] PK toàn hệ cho dòng mới: **mỗi trạm một dải + sequence cục bộ + CHECK**.
  - site_no: tayninh 1, hcm 2, cantho 3, dongnai 4. Dải trạm = site_no·10^6+1 .. site_no·10^6+999.999 (tayninh 1.000.001–1.999.999, hcm 2.000.001–2.999.999, …). Theo tiền lệ lab07 `CREATE SEQUENCE new_order_id START 1000001`.
  - Mỗi trạm 3 sequence: `patient_id_seq`, `visit_id_seq`, `prescription_id_seq` — START đầu dải, MAXVALUE cuối dải, NO CYCLE.
  - INSERT gọi `nextval('<bảng>_id_seq')` trực tiếp (cách lab07); KHÔNG gắn DEFAULT vào cột → định nghĩa bảng giữ nguyên như CSDL đối chứng (quy tắc 6).
  - CHECK mỗi trạm: `id <= max gốc OR id BETWEEN đầu dải AND cuối dải`; max gốc patient 20000, visit 80000, prescription 200000 (đều < 10^6, INTEGER đủ).
  - Phân vai: sequence = chống trùng trong 1 trạm (nextval nguyên tử, không khoá bảng; ROLLBACK để lại lỗ — chấp nhận); dải rời nhau = chống trùng giữa trạm, không trạm nào hỏi trạm nào (D8 tắt máy B, trạm còn lại vẫn insert); CHECK = chặn id gõ tay ngoài dải.
  - Bảng con (visit_cardio, visit_eye, visit_blood, visit_eye_diagnosis, visit_blood_test) dùng visit_id cha → tự duy nhất. hospital/drug sao chép, không insert từ trạm.
  - Loại: sequence chung ở trung tâm (điểm chết đơn, vỡ D8); max(id)+1 (trùng khi chèn đồng thời, phải khoá bảng); INCREMENT 4 xen kẽ (khó đọc trạm nguồn, CHECK bằng %); UUID/khoá ghép (đổi kiểu/thêm cột — đề cấm).
  - Lập luận vấn đáp: sequence không thêm bảng/cột vào lược đồ quan hệ; là cơ chế sinh khoá mà Mục 3 + README bộ sinh yêu cầu nhóm tự bảo đảm.
- [2026-11-17] Ràng buộc mảnh (Mục 3 "Ràng buộc mảnh"): 3 loại CHECK + FK cục bộ.
  - **CHECK mảnh** — patient: `CHECK (home_province = '<trạm>')`. Bảng dẫn xuất (visit, prescription, visit_cardio/eye/blood, eye_diagnosis, blood_test) không CHECK được (vị từ nằm ở bảng cha, CHECK không đọc bảng khác, không thêm cột) → **FK thật cục bộ** con→cha bảo đảm đúng vùng bắc cầu. FK visit.hospital_id, prescription.drug_code → bản sao cục bộ. Khác lab02 (chỉ PK, không FK).
  - **CHECK dải PK** — patient_id/visit_id/prescription_id: `id <= max gốc OR id BETWEEN dải trạm` (xem quyết định PK). Dòng mới lấy id theo dải của **trạm lưu** (tỉnh cư trú bệnh nhân), không theo tỉnh bệnh viện. VD bệnh nhân 14201 (cantho) khám BV 15 (hcm) → ghi trạm cantho, visit_id 3000001.
  - **CHECK jsonb** — visit.result theo specialty, **chỉ kiểm đủ key** (không kiểm kiểu): cardio `?& {bp_systolic,bp_diastolic,heart_rate,ecg}`; eye `{va_left,va_right,iop_mmhg,diagnoses}`; blood `{wbc,rbc,glucose,tests}`; specialty khác → false. Mục đích: lượt cardio thiếu bp_systolic làm Q4 ≠ Q5 (D5).
  - Giới hạn: CHECK không so jsonb với visit_cardio/eye/blood… → khớp nhau do giao diện ghi cùng giao dịch + truy vấn so trong `make check`. UPDATE home_province bị CHECK chặn — chuyển tỉnh = di dời cả hồ sơ (đề không yêu cầu, nêu khi vấn đáp).
  - Ví dụ kiểm demo (dữ liệu thật): ① visit 14201/BV15 ghi trạm cantho → OK; ② ghi nhầm trạm hcm → lỗi FK patient; ③ patient cantho chèn vào hcm → lỗi patient_frag_ck; ④ cardio mang jsonb mắt → lỗi visit_result_ck; ⑤ visit_id 2000050 chèn vào cantho → lỗi visit_id_ck.
- [2026-11-17] Lý do chia visit theo tỉnh cư trú (không theo bệnh viện), số đo: Q1 1464 lượt = BV tayninh 1359 + hcm 41 + cantho 36 + dongnai 28 → chia theo BV thì 105 lượt ở trạm khác, Q1 buộc Foreign Scan (vi phạm ràng buộc 3). Q2 gộp theo tỉnh cư trú → 2 giai đoạn. FK visit.patient_id cục bộ (chia theo BV: 5724 FK chéo trạm). Q4: 248/7516 bệnh nhân có lượt cardio ≥140 ở nhiều tỉnh → chia theo BV đếm trùng. Giá: Q3 hỏi 4 trạm (đề dán nhãn "liên vùng" ở D4). Thực tế: khớp mô hình hồ sơ theo người/nơi cư trú (BHYT, hồ sơ sức khỏe cá nhân), khác EMR theo bệnh viện — suy luận của Claude, đề không nói thẳng.
- [2026-11-17] Q2 tiền thuốc = `SUM(prescription.quantity * drug.price)` theo patient.home_province, visit_date năm 2025 (không nhân days). Đáp án đối chứng: tayninh 148.205.540.000 · hcm 155.980.326.500 · cantho 83.289.105.000 · dongnai 51.923.362.500 · tổng 439.398.334.000.
- [2026-11-17] `all_*` — chốt: view UNION ALL (bảng cục bộ tayninh + foreign table schema hcm/cantho/dongnai) cho 8 bảng bị chia. Loại partitioned table: là bảng mới (vi phạm quy tắc 6) + visit/prescription/bảng con không có cột phân vùng. Quy tắc viết: **truy vấn chỉ lọc 1 bảng → dùng all_*; truy vấn cần join các bảng bị chia → viết 4 nhánh theo trạm (join + gộp đẩy nguyên khối xuống trạm)**. Q1 bảng cục bộ; Q3 `all_visit WHERE hospital_id = ANY(ARRAY(SELECT ... province='tayninh'))` (xa trả 43/17/17); Q4 `SELECT DISTINCT patient_id FROM all_visit WHERE ...` (xa trả 3382/1769/1129); Q2, Q5 4 nhánh UNION ALL. Lý do Q2: viết thẳng trên view phải kéo ~181k dòng từ 3 trạm xa (prescription 71622/37379/23786 không lọc được + visit 2025 19179/10133/6284 + patient), fetch_size 100 → hcm ~980 FETCH × (5+30) ms ≈ 34 s (ước tính); 2 giai đoạn: 1 dòng/trạm. Q5 trên view phải kéo cả all_visit để lấy patient_id. Server: fetch_size 10000, async_capable true. IMPORT cả hospital/drug của từng trạm xa để join đẩy xuống. Cần đo EXPLAIN xác nhận đẩy xuống. Đúng đắn: bệnh nhân rời nhau giữa trạm (patient chia theo home_province, visit dẫn xuất) → tổng/đếm từng trạm rồi cộng = kết quả toàn hệ, không đếm trùng.
## Cần review
- [2026-11-16] Kiểm tra máy qua SSH (user labsoe, key ~/.ssh/id_ed25519, vào qua OpenVPN):
  .201 labsoe-05: Ubuntu 24.04, 12 CPU, 7 GB RAM, Docker 29.8.2 (labsoe trong nhóm docker), psql 18.4, đã có PostgreSQL host nghe 127.0.0.1:5432 → container dùng cổng khác. NIC LAN = wlo1 (Wi-Fi). tc có. sudo cần mật khẩu.
  .202 labsoe-07: Ubuntu 22.04 (khác .201), 12 CPU, 7 GB, Docker 29.8.2 OK, không có psql, NIC wlo1 (Wi-Fi), tc có. sudo cần mật khẩu.
  .203 labsoe-06: user **labsit06** (khác 2 máy kia), Ubuntu 22.04, 12 CPU, 7 GB, Docker 29.8.2 OK, không psql, wlo1 Wi-Fi, tc có, sudo cần mật khẩu, tailscale0 100.64.0.4.
  RTT LAN đo từ .201 (ping ×5): →.202 avg 5,17 ms (mdev 0,59); →.203 avg 5,81 ms (mdev 0,90). Trễ nền Wi-Fi ~5 ms, đáng kể so với 30 ms netem → N3 phải trừ nền.
  Cả .201/.202 đã có tailscale0 (100.64.0.2/.3) thuộc tailnet KHÁC tailnet của laptop (laptop đang ở tailnet công ty) → SSH timeout.
  Rủi ro: LAN là Wi-Fi → jitter làm nhiễu N3; netem phải gắn đúng card wlo1 hoặc trong container.

# Tasks
## Đang làm
Cơ chế triển khai (Claude chốt 2026-11-17, dựa kiểm máy):
- Laptop không có rsync/make → `scripts/deploy.sh` (bash, Git Bash) đẩy repo bằng `tar | ssh` vào `~/cs5104_final` trên cs-a/cs-b/cs-c, rồi `ssh <host> 'cd ~/cs5104_final && make up MACHINE=<X>'`.
- Mọi bước sau `up` chạy **trên máy A** (python3 3.12, psql 18, venv `~/cs5104-venv` có psycopg 3.3.6), nói chuyện với trạm B/C qua cổng LAN (trust). A không SSH được sang B/C (host key + key chưa trao) → không cần: B/C chỉ cần `make up MACHINE=B|C`.
- B/C chỉ có python3.10 (không tomllib) → `make up` trên B/C không được cần Python; dùng `docker compose --profile <X>`.
- CSDL đối chứng = container thứ 5 `ref` trên A, cổng 5437 (KHÔNG đụng PostgreSQL host 5432).
- Trung tâm gọi mọi trạm xa (kể cả dongnai cùng máy) qua `192.168.80.201|202|203:<cổng>` → delay-on chỉ cần netem trong container tayninh, **lọc gói đi tới cổng 5434/5435/5436** (tc prio + u32 dport) → mỗi vòng khứ hồi trung tâm→trạm xa +30 ms, client trên A→tayninh không bị trễ. Không cần SSH sang B/C.

- [x] **T1 — XONG 2026-11-17, Claude kiểm trên máy thật:** 5 container healthy (A: tayninh/dongnai/ref; B: hcm; C: cantho); `make load` 12 s; 40/40 số đếm khớp bảng số đo, ref 476.885; demo ① OK (nextval → 3000001), ②–⑤ báo đúng lỗi visit_patient_id_fkey / patient_frag_ck / visit_result_ck / visit_id_ck; sequence 3000001–3999999 ở cantho. `make up` chạy lại idempotent. Ghi chú: ROLLBACK vẫn tiêu số sequence (lỗ, đã chấp nhận).
- [x] **T1 [Codex] Hạ tầng + lược đồ + nạp mảnh** (`make up / data / load / down`)
      Mục tiêu: 5 container PG18 chạy, 4 trạm có đúng mảnh + ràng buộc, `ref` có toàn bộ dữ liệu.
      File tạo:
      - `deploy.toml`: [sites.tayninh] machine="A" ip="192.168.80.201" port=5433 site_no=1 central=true; hcm B .202 5434 2; cantho C .203 5435 3; dongnai A .201 5436 4; [ref] A .201 5437; dbname="hospital"; [machines] A/B/C với ssh alias cs-a/cs-b/cs-c.
      - `docker/Dockerfile` = lab01 (`FROM postgres:18` + iproute2), image `cs5104/postgres-netem:18` (A đã có; B/C phải build).
      - `docker-compose.yml` (project name `cs5104final`): service tayninh, dongnai, ref (profile A), hcm (profile B), cantho (profile C); container_name `final_<site>`; cap_add NET_ADMIN; command `postgres -c listen_addresses=*`; env POSTGRES_HOST_AUTH_METHOD=trust, POSTGRES_DB=hospital; port `<p>:5432`; named volume; healthcheck pg_isready (khuôn `labs/lan/docker-compose.yml`).
      - `Makefile`: `up MACHINE=A|B|C` → `docker compose --profile $(MACHINE) up -d --build --wait`; `down MACHINE=..` → `down -v`; `data` → `PYTHONUTF8=1 python3 CS5104_Project_DataGen/de01_hospital/generate.py --size lab --out data/lab` (bỏ qua nếu đã có summary.json); `load` → `scripts/load.sh`.
      - `sql/schema_central.sql`: 10 bảng, kiểu **đúng đề trang 6** (hospital(hospital_id integer, name text, province text); drug(drug_code text, name text, unit text, price numeric); patient(patient_id integer, full_name text, birth_year smallint, gender char, home_province text); visit(visit_id integer, patient_id integer, hospital_id integer, specialty text, visit_date date, result jsonb); prescription(prescription_id integer, visit_id integer, drug_code text, quantity integer, days smallint); visit_cardio(visit_id, bp_systolic smallint, bp_diastolic smallint, heart_rate smallint, ecg_rhythm text, ecg_qt_ms smallint); visit_eye(visit_id, va_left numeric, va_right numeric, iop_mmhg smallint); visit_eye_diagnosis(visit_id, seq smallint, diagnosis text) PK(visit_id,seq); visit_blood(visit_id, wbc numeric, rbc numeric, glucose numeric); visit_blood_test(visit_id, code text, value numeric, unit text) PK(visit_id,code)). PK + 9 FK. Không DEFAULT, không cột thừa. Dùng chung cho ref và 4 trạm.
      - `sql/site_constraints.sql` (biến psql `:'site'`, `:site_no`): CHECK `patient_frag_ck`, `patient_id_ck`/`visit_id_ck`/`prescription_id_ck` (`id <= 20000|80000|200000 OR id BETWEEN site_no*10^6+1 AND site_no*10^6+999999`), `visit_result_ck` (CASE specialty, `?&`, xem Đã chốt 2026-11-17); 3 sequence `<bảng>_id_seq` START dải MAXVALUE cuối dải NO CYCLE. FK đã có trong schema.
      - `scripts/load.sh` (chạy trên A): (1) ref: drop+tạo schema, `\copy ... FROM data/lab/<t>.csv (FORMAT csv, HEADER)` 10 bảng; (2) mỗi trạm: drop+tạo schema, rồi lấy mảnh từ ref bằng semijoin qua ống `psql ref -c "\copy (SELECT …) TO STDOUT (FORMAT csv)" | psql trạm -c "\copy t FROM STDIN (FORMAT csv)"`, thứ tự cha→con: hospital, drug (toàn bộ); patient WHERE home_province=site; visit JOIN patient; prescription/visit_cardio/eye/blood qua visit→patient; eye_diagnosis, blood_test tương tự; (3) site_constraints.sql; (4) ANALYZE. Host/port lấy từ deploy.toml (python3 tomllib trên A). Idempotent.
      - `scripts/deploy.sh` (Git Bash trên laptop): tar repo (loại `data/`, `.git`, `*.pdf`, `CS5104_Project_DataGen/*/output`) | ssh mỗi máy → `~/cs5104_final`; tuỳ chọn `--up` chạy `make up MACHINE=X` từ xa.
      - `.gitignore`: data/, `CS5104_Project_DataGen/*/output/`, `*.pdf`, `__pycache__/`.
      Ràng buộc: không sửa generate.py; không động cổng 5432 / container của labs (`cs5104_pg`, `str_*`, `citus_*`); không lưu mật khẩu; không sudo.
      Kiểm chứng (Claude chạy qua SSH): đếm dòng mỗi trạm = bảng số đo (patient 6819/7172/3683/2326; visit 26907/28697/14936/9460; prescription 67213/71622/37379/23786; visit_cardio 12132/12787/6814/4210; visit_eye 9440/10169/5168/3291; visit_blood 5335/5741/2954/1959; eye_diag 18862/20260/10371/6625; blood_test 13349/14515/7439/4934); hospital 30, drug 500 mọi trạm; ref đủ 476.885 dòng; 5 ví dụ demo trong Đã chốt ra đúng lỗi.

- [ ] **T2 [Codex] Liên kết trung tâm + truy vấn + kiểm tra** (`make link / check`) — sau T1
      - `sql/link.sql` (chạy trên tayninh): `CREATE EXTENSION postgres_fdw`; 3 server hcm/cantho/dongnai (host/port từ deploy.toml, dbname hospital, fetch_size '10000', async_capable 'true'); user mapping postgres; schema hcm/cantho/dongnai + `IMPORT FOREIGN SCHEMA public FROM SERVER x INTO x` (gồm hospital/drug); 8 view `all_<bảng>` UNION ALL. Idempotent.
      - `sql/queries/q1..q5.sql` bản trung tâm theo quy tắc Đã chốt `all_*`: Q1 bảng cục bộ; Q2 4 nhánh, `SUM(quantity*price)`; Q3 `all_visit` + `hospital_id = ANY(ARRAY(...province='tayninh'))`; Q4 DISTINCT patient_id trên `all_visit` với specialty='cardio' AND `(result->>'bp_systolic')::int >= 140`; Q5 4 nhánh visit_cardio JOIN visit. Kèm `sql/queries_ref/q1..q5.sql` bản tập trung chạy trên ref. Mốc: 3/2026 = [2026-03-01, 2026-04-01); năm 2025.
      - `scripts/check.py` (chạy trên A, psycopg từ ~/cs5104-venv): (a) 3 quy tắc Mã 2.1 cho 8 bảng bị chia — đầy đủ + tái tạo (so all_* với ref, EXCEPT ALL 2 chiều hoặc so hash từng dòng), rời nhau (GROUP BY khoá HAVING count>1 trên all_*); (b) đúng vùng patient; (c) FK mồ côi = 0 mỗi trạm; (d) hospital/drug 4 trạm giống hệt ref; (e) jsonb ↔ bảng quan hệ khớp; (f) Q1–Q5 trung tâm = ref; (g) EXPLAIN Q1 không có "Foreign Scan". In PASS/FAIL, exit≠0 nếu FAIL.
      Kiểm chứng: `make link && make check` trên A toàn PASS; Q1 = 1464, Q3 = 1436, Q4 = Q5 = 7516, Q2 khớp 4 số Đã chốt.

## Chờ
- [ ] T3 bench/delay-on/delay-off/results.csv + EXPLAIN; T4 entry UI; T5 dashboard; T6 `make all`; README (Claude) — viết sau khi T1–T2 chạy.
## Xong
- [x] [Claude, 2026-11-17] `docs/design.html` — bản nháp M1 trả lời đủ 6 câu Mục 3 + trung tâm/Q1–Q5 + phương án loại + rủi ro.
- [x] [Codex, 2026-11-16] Bỏ n-n khỏi sơ đồ: còn 9 cạnh FK trực tiếp (6 × 1-n, 3 × 1-1). HTML 111 KB.
- [x] [Codex, 2026-11-16] Rút gọn tab bảng: bỏ mini + thống kê cột; mỗi tab còn mô tả, từ điển cột PK/FK, quan hệ, 10 dòng lab. HTML 116 KB.
- [x] [Codex, 2026-11-16] Class diagram SVG (10 class, 9 cạnh trực tiếp + 2 n-n) trong data_explorer.html. Số đo khớp Claude đếm độc lập. n-n: patient–hospital 0..9 bv/bn; visit–drug 0..10 thuốc/visit.
- [x] [Codex, 2026-11-16] Trang `docs/data_explorer.html` + `scripts/explore_data.py`. Claude đối chiếu độc lập: khớp.
      Q2 (năm 2025, theo tỉnh cư trú) cách A = SUM(quantity*price): tayninh 148.205.540.000 · hcm 155.980.326.500 · cantho 83.289.105.000 · dongnai 51.923.362.500 · tổng 439.398.334.000. Cách B (×days): tổng 6.815.459.127.500.
      Q4 = Q5 = 7516 bệnh nhân; jsonb ↔ bản quan hệ lệch 0 dòng.
      Dòng/trạm (đã gồm bản sao hospital+drug = 530): tayninh 160.587 · hcm 171.493 · cantho 89.274 · dongnai 57.121.
      Máy A/B: PA1 160.587/317.888 · PA2 (A=tayninh+cantho) 249.861/228.614 · PA3 (A=tayninh+dongnai) 217.708/260.767.
      Max id: patient 20000, visit 80000, prescription 200000. 10.871 cặp (visit_id, drug_code) lặp — hợp lệ vì PK là prescription_id.
- [x] Đọc đề (trang 1–8) và bộ sinh Đề 1; chạy mini + lab, đối chiếu summary.json.
