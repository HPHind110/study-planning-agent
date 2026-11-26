# API lập lịch học kỳ

Địa chỉ mặc định `http://127.0.0.1:8102`. JSON UTF-8, ngày ISO, thời điểm địa phương dạng `YYYY-MM-DD HH:MM`. Bắt đầu và kết thúc đúng biên được phép. Các API v1 tiếp tục dùng được.

## Việc và cấu hình

`POST /tasks` và `PUT /tasks/{id}` nhận thêm `start_at` (null hoặc trước due), `deadline_type` (hard mặc định, hoặc soft), `notes` (chuỗi hoặc null). PUT vẫn cần các trường bắt buộc trước đây. Client cũ bỏ qua trường mới khi sửa sẽ giữ giá trị đã lưu. GET /tasks trả thêm ba trường. Cả hai loại hạn đều chặn lịch sau hạn.

```json
{"name":"Sửa báo cáo sau thuyết trình","course":"Kho dữ liệu","due":"2026-12-21 22:00","start_at":"2026-12-15 08:00","deadline_type":"soft","estimate":180,"priority":4,"notes":"Áp dụng nhận xét của nhóm phản biện."}
```

Ví dụ `POST /plans/replan`. windows là mảng 7 chuỗi từ T2 đến CN như v1. weekday_caps là mảng 7 giá trị, null kế thừa cap, 0 nghỉ. overrides ghi đè các thuộc tính được chỉ định của ngày. Khi gửi cả bản đồ overrides mới, nó thay thế bản đồ trước. off chặn cả ngày. horizon_end tính cả ngày cuối; gửi null để quay lại cửa sổ trượt 90 ngày. changes hỗ trợ id, due, left, priority, start_at và deadline_type. start_at null xóa giới hạn bắt đầu.

```json
{"settings":{"horizon_end":"2027-01-10","weekday_caps":[120,60,120,60,120,180,0],"overrides":{"2026-11-27":{"windows":"08:00-12:00, 19:00-21:00","cap":210},"2027-01-02":{"cap":240,"windows":"08:00-12:00, 14:00-17:00"}}}}
```

## Sự kiện

| Endpoint | Kết quả |
|---|---|
| POST /events | 201, bản ghi có ID mới |
| GET /events | Danh sách quy tắc gốc |
| PUT /events/{id} | Thay nội dung sự kiện |
| DELETE /events/{id} | Xóa sự kiện và xếp lại lịch |

```json
{"name":"Lớp tiếng Anh","start":"2026-12-01 20:00","end":"2026-12-01 22:00","repeat":"weekly","until":"2027-01-01"}
```

repeat mặc định once. until chỉ dùng cho weekly và bao gồm cả ngày đó. Mỗi lần xuất hiện lấy thứ và giờ từ start/end. Sự kiện có thể chồng nhau, dashboard cảnh báo và trừ hợp các khoảng bận.

## Gói JSON và thay thế an toàn

| Endpoint | Công dụng |
|---|---|
| GET /planning/export | Gói kế hoạch có version, courses, tasks, events, settings |
| GET /planning/export?backup=true | Bản sao đầy đủ có tiến độ, lịch và nhật ký |
| POST /planning/preview | Kiểm tra bản sao trong RAM. Trả diff, duplicates, errors, warnings, workload và token nếu hợp lệ |
| POST /planning/import | Gửi lại đúng nội dung preview kèm token để ghi |
| GET /planning/backups/{id} | Tải bản sao trước thay đổi được lưu trong SQLite |

Ví dụ đầy đủ cho preview. Các bản ghi có thể tham chiếu tới ID khác cùng gói bất kể thứ tự hoặc ID đã tồn tại. ID task và ID event có không gian tên riêng.

```json
{
  "mode":"append",
  "document":{
    "version":2,
    "tasks":[
      {"id":"draft","course":"Học phần mẫu","name":"Bản thảo","due":"2026-12-06 18:00","estimate":90,"deadline_type":"soft"},
      {"id":"revise","course":"Học phần mẫu","name":"Sửa bài","start_at":"2026-12-15 08:00","due":"2026-12-21 22:00","estimate":60,"deps":["draft"]}
    ],
    "events":[{"id":"talk","name":"Thuyết trình","start":"2026-12-14 10:00","end":"2026-12-14 11:00"}]
  }
}
```

- **append** thêm ID mới. ID đã có cùng nội dung được liệt kê là trùng. ID trùng nhưng nội dung khác, ID lặp trong cùng tệp, chu trình hoặc thiếu tiên quyết làm hủy lần nhập. ID là căn cứ nhận dạng, hai việc trùng tên vẫn có thể là hai việc khác nhau.
- **replace** cần scope tường minh. Ví dụ `{"courses":["Học phần mẫu"],"event_ids":["talk"],"settings":false}`. Các việc thuộc môn trong scope nhưng thiếu trong gói sẽ bị xóa. Với sự kiện chỉ các ID trong scope mới được thay/xóa. Cập nhật một ID đã có giữ nguyên left và nhật ký. Dữ liệu ngoài scope được giữ; nếu việc ngoài scope mất tiên quyết thì toàn bộ yêu cầu bị từ chối. Chỉ ghi cấu hình nếu `scope.settings=true`. Các trường cấu hình cấp trên không được gửi sẽ được giữ.
- **restore** gửi nội dung của bản sao đầy đủ vào document, chọn `scope: {"full_restore":true}`. Có preview và xác nhận riêng. Khôi phục lịch sử và số phút còn lại, tính lại các buổi tương lai theo đồng hồ hiện tại. Bản sao cũng được tạo trước khi khôi phục.
- **Token** gắn với yêu cầu và trạng thái dữ liệu. Nếu đã có thay đổi sau preview, import trả 409; xem trước lại. Lỗi validation trả 422 khi commit. Preview có thể trả HTTP 200 với errors khi gói không hợp lệ. Cấu trúc bao ngoài sai trả 422.
- **Giao dịch** backup và cập nhật dùng cùng một giao dịch SQLite. Nếu bất kỳ bước ghi nào lỗi, cả hai cùng rollback. Lịch sử các backup được liệt kê trong `GET /dashboard` tại backups, mới nhất trước.

## Phân tích

`GET /dashboard` trả thêm events, recent_risks và analysis. remaining, scheduled, unscheduled, capacity tính bằng phút. dates/weeks gồm required (phút còn lại của các việc đến hạn trong kỳ), scheduled và capacity. weeks dùng thứ hai đầu tuần. courses nhóm phút còn lại. deadlines so sánh nhu cầu lũy kế với quỹ phút ước tính đến đúng thời điểm hạn. risks chứa task, minutes, status, causes và recommendation. status nhận overdue, deferred hoặc unscheduled. Một nhiệm vụ hạn ngoài kỳ vẫn được xếp sớm nếu còn chỗ; chỉ phần chưa xếp mới được báo deferred. Hạn mềm và mọi gợi ý điều chỉnh cần được người dùng duyệt.

