# Ứng dụng dò vé số Nhật

Ứng dụng web dùng để dò và tra cứu kết quả xổ số Nhật, dữ liệu tự động lấy từ website Mizuho.

## Tính năng

- Dò tự động cho nhóm xổ số chọn số:
  - Mini Loto
  - Loto 6
  - Loto 7
- Dò tự động cho vé truyền thống theo `tổ + số vé`:
  - Trả kết quả trúng/không trúng
  - Liệt kê các giải trúng
  - Tính tổng tiền thưởng
- Tra cứu kết quả cho nhóm vé truyền thống (`tsujyo`), gồm:
  - `全国自治` (`zenkoku`)
  - `ジャンボ` (`jumbo`)
  - `東京都` (`tokyo`)
  - `近畿` (`kinki`)
  - `地域医療等振興自治` (`chiiki`)
  - `関東・中部・東北自治` (`kct`)
  - `西日本` (`nishinihon`)
- Chọn kỳ quay cụ thể hoặc để trống để lấy kỳ mới nhất.
- Hiển thị đầy đủ link nguồn dữ liệu gốc.

## Nguồn dữ liệu

- Nhóm chọn số:
  - `https://www.mizuhobank.co.jp/takarakuji/apl/txt/<game>/name.txt`
  - `https://www.mizuhobank.co.jp/retail/takarakuji/loto/<game>/csv/<file>.CSV`
- Nhóm vé truyền thống:
  - `https://www.mizuhobank.co.jp/retail/takarakuji/tsujyo/<type>/csv/<type>.csv`

## Cài đặt

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Chạy ứng dụng

```bash
python app.py
```

Mở trình duyệt tại: `http://127.0.0.1:5000`

## Chạy test

```bash
pytest
```

## Lưu ý

- Dữ liệu lấy trực tiếp từ CSV public của Mizuho, định dạng có thể thay đổi theo thời gian.
- Logic dò vé truyền thống đã hỗ trợ các điều kiện phổ biến: khớp tổ/số, khớp đuôi, giải trước-sau, giải khác tổ cùng số.

## Rate limit

Ứng dụng có chặn tần suất request theo IP (in-memory):

- `RATE_LIMIT_ENABLED` (mặc định: `true`)
- `RATE_LIMIT_WINDOW_SECONDS` (mặc định: `60`)
- `RATE_LIMIT_MAX_REQUESTS_PER_WINDOW` (mặc định: `120`)
- `RATE_LIMIT_POST_ROOT_MAX_REQUESTS_PER_WINDOW` (mặc định: `20`)

Khi vượt ngưỡng, server trả về HTTP `429` và header `Retry-After`.

## Deploy AWS

- Simple AWS deploy guide and scripts: `deploy/aws/README.md`
