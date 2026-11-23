# HTTP API

Địa chỉ mặc định `http://127.0.0.1:8102`. Giờ hạn và giờ buổi học theo đồng hồ địa phương của máy chạy Agent. Các lệnh ghi chạy trong giao dịch SQLite. Một thay đổi không hợp lệ sẽ hủy toàn bộ yêu cầu đó.

| Endpoint | JSON gửi | HTTP thành công và JSON trả về |
|---|---|---|
| GET /health | Không có | 200 · `{"status":"ok"}` sau khi đọc được kho dữ liệu |
| POST /tasks | TaskInput | 201 · Task |
| GET /tasks | Không có | 200 · mảng Task, ban đầu là `[]` |
| POST /plans/generate | Không cần body | 200 · Plan được tính lại theo thời điểm gọi |
| POST /plans/replan | Replan, có thể là `{}` | 200 · Plan sau khi áp dụng tất cả thay đổi |
| GET /plans/current | Không có | 200 · Plan đã lưu gần nhất, gồm cả thay đổi từ desktop. Với DB đời cũ, lần đọc đầu khởi tạo snapshot |

## TaskInput và Task

Dashboard nằm ở `GET /`. Giao diện đọc dữ liệu qua `GET /dashboard` (đồng bộ các buổi đã qua và trả tasks, courses, settings, sessions, history, warnings). Các thao tác được bổ sung gồm `POST/PATCH/DELETE /courses`, `PUT/DELETE /tasks/{key}` và `POST /progress`. Khi ghi tiến độ, gửi task (ID), actual (phút đã học), remaining (phút còn lại) và tùy chọn start nếu ghi cho buổi đang diễn ra. Các endpoint lập lịch trong bảng trên cũng được dùng trực tiếp từ giao diện.

| Trường | Kiểu và ý nghĩa |
|---|---|
| name, course | Chuỗi bắt buộc sau khi cắt khoảng trắng, 1–250 ký tự. Tên môn mới được tạo tự động |
| due | Bắt buộc, ngày giờ hợp lệ dạng YYYY-MM-DD HH:MM |
| estimate | Bắt buộc, số nguyên 1–100000 phút |
| kind | Bài tập (mặc định), Kỳ thi hoặc Mục tiêu |
| priority, difficulty | Số nguyên 1–5, mặc định 3 |
| deps | Mảng ID việc tiên quyết đã tồn tại, mặc định [] |
| id, left | Chỉ ở Task trả về. ID dạng chuỗi và số phút còn lại, ban đầu bằng estimate |

## Replan và Plan

`changes` là mảng các đối tượng có `id` bắt buộc và các trường mới tùy chọn `due`, `left` (0–100000), `priority`. Đặt left bằng 0 để đánh dấu xong. `skip` là mảng các cặp `task`, `start` lấy từ lịch vừa đọc. Agent tránh xếp lại vào buổi đã bỏ. `settings` nhận các trường trong bảng dưới. Cả ba phần đều tùy chọn.

| Trường settings | Giá trị |
|---|---|
| windows | Mảng đúng 7 chuỗi thứ hai đến chủ nhật, ví dụ một ngày là "08:00-10:00, 19:00-21:00". Chuỗi trống là ngày nghỉ |
| off | Mảng ngày bận YYYY-MM-DD. Khi gửi sẽ thay thế toàn bộ danh sách |
| cap | Trần phút học mỗi ngày, 1–720 |
| block | Phút tối đa mỗi buổi, 5–120 |
| rest | Phút nghỉ giữa các buổi, 1–60 |

Ví dụ Plan (ID rút gọn để minh họa):

```json
{"sessions":[{"task":"abc","start":"2026-12-01 19:00","end":"2026-12-01 19:40","minutes":40,"reason":"Hạn xét 2026-12-04 22:00 · còn 40 phút · ưu tiên 3/5 · khó 3/5"}],"warnings":[]}
```

Nếu không đủ giờ, phản hồi vẫn là 200 và warnings cho biết phần việc còn thiếu. Dữ liệu đầu vào sai trả 422, ID cần sửa không tồn tại trả 404, buổi muốn bỏ đã đổi trả 409. Các lỗi có trường `detail` là chuỗi hoặc danh sách lỗi kiểm tra đầu vào. Schema đầy đủ và các giá trị mặc định có tại [OpenAPI JSON](http://127.0.0.1:8102/openapi.json).

## Ví dụ PowerShell

```powershell
$base = 'http://127.0.0.1:8102'
$task = @{name='On PDE'; course='PDE'; estimate=90; due=(Get-Date).AddDays(4).ToString('yyyy-MM-dd HH:mm')}
$created = Invoke-RestMethod "$base/tasks" -Method Post -ContentType 'application/json' -Body ($task | ConvertTo-Json)
Invoke-RestMethod "$base/plans/generate" -Method Post
$change = @{changes=@(@{id=$created.id; left=45}); settings=@{block=25}}
Invoke-RestMethod "$base/plans/replan" -Method Post -ContentType 'application/json' -Body ($change | ConvertTo-Json -Depth 6)
Invoke-RestMethod "$base/plans/current"
```

