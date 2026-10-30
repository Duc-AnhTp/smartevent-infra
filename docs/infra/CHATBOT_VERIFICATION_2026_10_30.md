# Khắc phục audit và kiểm chứng 4 repo — 30/10/2026

## Phạm vi đã sửa

| Repo | Thay đổi |
|---|---|
| infra | Sửa FK `knowledge_active.index_id`; bootstrap có transaction; migration bảo toàn dữ liệu và bổ sung role còn thiếu; health kiểm tra schema/FK; policy dense `fail_closed` hoặc `bm25` tường minh; CI dùng pgvector/PostgreSQL cô lập |
| backend | Search không có filter cũng lấy giá theo batch và cùng Clock; sort ổn định; API ghế mặc định chỉ AVAILABLE, chế độ sơ đồ đầy đủ tường minh; lỗi query param trả 400 có cấu trúc; test binding UTC/offset/encoded offset; test query count PostgreSQL; kiểm tra Flyway dùng DB test riêng |
| web | Phân biệt client abort (499) với timeout (504); giữ PUBLIC_HELP; giữ mã HTTP và error metadata an toàn; kiểm tra sâu events/actions/citations; booking yêu cầu rõ sơ đồ đầy đủ; build Windows riêng; CI Ubuntu/Windows |
| AI | Giữ và công bố `degraded_bm25` khi reader tri thức dự phòng; bổ sung test không cần mạng; cập nhật manifest |

Không mở các gate mặc định. Không đổi model hay giả lập kết quả nghiệm thu model.

## Điều chỉnh quan trọng theo nghiệp vụ

API `/areas/{areaId}/seats/available` trước đây trả cả HELD/SOLD/BLOCKED vì web
dùng kết quả đó làm sơ đồ ghế. Lọc bỏ những ghế này ở mọi nơi sẽ làm mất bố cục
và trạng thái hiển thị của web. Hợp đồng mới:

- Không có query param: chỉ AVAILABLE, sắp xếp theo hàng/số ghế.
- `includeUnavailable=true`: trả sơ đồ đầy đủ, giữ trạng thái thực tế và thời hạn giữ.
- Web đặt vé chủ động gửi param này, tiếp tục vô hiệu hóa ghế không AVAILABLE.
- Controller giữ guard sự kiện cha PUBLISHED và quyền owner/admin đã có.
- Gateway AI chỉ gọi endpoint mặc định và tiếp tục lọc AVAILABLE; không được
  dùng snapshot để cam kết còn vé tại thời điểm thanh toán.

Kiểm tra Flyway cũ phụ thuộc `SPRING_DATASOURCE_URL` của ứng dụng và chỉ in kết
quả. Đã chuyển sang nhóm `postgres`, dùng PostgreSQL Testcontainers riêng và
assert migrate/validate thành công. Không dùng database cấu hình của ứng dụng
để chạy kiểm thử migration. CI backend hiện chạy cả `test` và `postgresTest`.

## Kết quả đã chạy trong môi trường hiện tại

| Kiểm tra | Kết quả và giới hạn |
|---|---|
| Web unit/regression | 134/134 PASS |
| Web typecheck | PASS |
| Web lint | PASS, còn 19 warning có sẵn ngoài phần sửa |
| Web format | PASS; hỗ trợ line ending Windows/Linux, loại thư mục sinh từ local build |
| Web local build | PASS, 29 trang được tạo; dùng Webpack và `.next-local` |
| Web khởi động | `start:local -- --hostname 127.0.0.1 --port 3100` báo Ready; HTTP probe từ agent bị EACCES nên chưa đánh dấu HTTP smoke PASS |
| Backend biên dịch | Toàn bộ main/test biên dịch thành công bằng javac với dependency cache, `-parameters` và Lombok |
| Backend test trọng tâm | 22/22 PASS qua JUnit Launcher thật, gồm Spring MVC binding và error response |
| Backend chạy rộng ban đầu | 244 ca: 240 đạt, 4 lỗi môi trường/config; ca Flyway sau đó được chuyển sang DB Testcontainers cô lập, biên dịch lại thành công; ba ca HTTP thật còn bị chặn loopback |
| AI regression liên quan | 37/37 PASS; Ruff và mypy PASS |
| Infra unit | 5 PASS, 2 integration tests SKIPPED vì chưa có DB test/driver; Ruff và YAML parsing PASS |
| PostgreSQL/pgvector, Docker, E2E bốn repo | Chưa nghiệm thu; Docker API trả permission denied trong môi trường agent |

Không diễn giải biên dịch thành chạy ứng dụng, MockMvc thành HTTP qua TCP,
hoặc CI workflow mới thành CI đã chạy thành công. Chưa có kết quả model inference,
held-out, browser Reset race hoặc rollback toàn stack trong đợt này.

## Cách build và chạy web trên Windows

Trong `smartevent-web`, dùng Node 24.13.1:

```powershell
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build:local
npm run start:local
```

Local build dùng `.next-local`, không copy standalone. Các lệnh `build` và
Docker/CI Linux vẫn dùng standalone như trước. Build mặc định trong sandbox này
bị lỗi Turbopack khi kết nối process PostCSS; Webpack standalone gặp EPERM khi
copy file. Không xóa output cũ hoặc thay cấu hình hệ thống để vượt các giới hạn đó.

## Kiểm chứng còn phải chạy trên host có đủ quyền

1. Trong AI, chạy full pytest với coverage >=90% và clean-wheel HTTP smoke.
2. Trong backend, chạy `./gradlew clean test postgresTest bootJar --no-daemon`.
   `postgresTest` dùng database cô lập. Kiểm tra mới bao gồm số SQL không tăng
   theo số event, giá/count/pagination, counter và ghế AVAILABLE.
3. Chạy workflow `Knowledge contracts` ở infra: nó tạo `knowledge_test` với
   pgvector, chạy DDL thật, kiểm tra FK, migration legacy lặp lại và role chỉ đọc.
   Sau đó cần kiểm tra ingest thực, restart/backup/restore và corpus được duyệt.
4. Dựng stack fixture cô lập; kiểm chứng tìm theo city/ngày/giá, FAQ có nguồn,
   không lộ DRAFT, zero-write, browser Reset A→B và rollback.
5. Chỉ sau khi có bằng chứng tương ứng mới duyệt profile bật tìm kiếm/RAG.

Sửa volume knowledge cũ theo `services/knowledge/README.md`, bắt đầu bằng backup.
Migration sẽ từ chối con trỏ legacy không ánh xạ được; không xóa dữ liệu hoặc
chọn ngẫu nhiên một index để làm cho health báo sẵn sàng.

## Trạng thái bàn giao

Code ở cả bốn working tree, chưa commit/push trong đợt sửa này. Các log trung gian
nằm trong output build bị git ignore. Hệ thống chưa đủ bằng chứng để tuyên bố
đã chạy thành công toàn stack trong sandbox hiện tại.

Web local đã được khởi động tại `http://127.0.0.1:3100`. Dừng bằng Ctrl+C ở tiến
trình tương ứng. Việc khởi động web không xác nhận backend/AI/knowledge đã được
kết nối, và không thay thế các kiểm tra PostgreSQL/E2E ở trên.
