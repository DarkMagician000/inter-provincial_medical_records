# CS5104 — Bộ sinh dữ liệu cho project nhóm cuối kỳ

Mỗi đề một thư mục. Nhóm chỉ dùng thư mục của đề mình.

| Đề | Thư mục | Seed |
| --- | --- | --- |
| 1 | `de01_hospital` | 731905 |
| 2 | `de02_university` | 284617 |
| 3 | `de03_bank` | 590243 |
| 4 | `de04_vehicle` | 168372 |
| 5 | `de05_insurance` | 846051 |
| 6 | `de06_hotel` | 402738 |
| 7 | `de07_logistics` | 957164 |
| 8 | `de08_agri` | 315829 |

## Cách chạy

Yêu cầu: Python 3.11 trở lên, không cần cài thêm thư viện.

```bash
cd de01_hospital
python3 generate.py --size mini   # bộ nhỏ (vài chục dòng mỗi bảng) để kiểm tra bằng mắt
python3 generate.py --size lab    # bộ dùng để đo (khoảng 1–3 giây)
```

Kết quả nằm ở `output/mini/` hoặc `output/lab/`:

- mỗi bảng của lược đồ tập trung một tệp `<bảng>.csv`, có dòng tiêu đề; cột `jsonb` ghi dạng chuỗi JSON; giá trị rỗng là `NULL`;
- `summary.json`: số dòng mỗi bảng, số dòng theo vùng, số dòng liên vùng, số dòng mỗi loại `jsonb`.

## Nạp vào PostgreSQL

Viết `schema_central.sql` đúng sơ đồ của đề, rồi nạp bảng cha trước, bảng con sau, ví dụ:

```sql
\copy patient FROM 'output/lab/patient.csv' WITH (FORMAT csv, HEADER true)
```

Bảng tên `transaction` (Đề 3) nên đặt trong ngoặc kép: `"transaction"`.

## Lưu ý

- **Không sửa `generate.py`.** Seed và tham số đã cố định theo đề; cùng seed thì cùng dữ liệu trên mọi máy, nên số liệu của nhóm phải khớp `summary.json`.
- Dữ liệu là **tập trung, chưa chia**. Việc chia thành mảnh và nạp vào từng trạm là phần việc của nhóm.
- Khoá chính trong dữ liệu sinh ra đánh số từ 1. Khi thêm dòng mới ở nhiều trạm, nhóm tự bảo đảm khoá không trùng (xem Mục 3 của đề).
- Tên người, địa chỉ là giả lập; không có dữ liệu thật.
