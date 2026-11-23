# Sổ học

Ứng dụng desktop tiếng Việt và HTTP API lập lịch tự học theo hạn, khối lượng và quỹ giờ cá nhân. Cả hai dùng chung thuật toán và cơ sở dữ liệu SQLite trong thư mục dự án.

## Chạy từ GitHub trên Windows

Cài Python 3.13 x64 có Python Launcher, Tkinter và pip. Trong PowerShell:

```powershell
git clone https://github.com/HPHind110/study-planning-agent.git
cd study-planning-agent
.\start-api.cmd
```

Lần đầu, launcher tạo môi trường `.venv` ngay trong dự án và cài FastAPI cùng Uvicorn. Mở http://127.0.0.1:8102/docs để gửi thử yêu cầu. Dùng Ctrl+C để dừng. Chạy giao diện desktop riêng bằng `.\start.cmd`. Nếu muốn giữ dữ liệu từ bản ZIP, đóng ứng dụng rồi sao chép thư mục `data` của bản cũ vào bản clone mới trước lần chạy đầu.

Hướng dẫn payload, mã phản hồi và ví dụ PowerShell nằm trong [API.md](API.md). Schema máy đọc được tại `GET /openapi.json`.

## Mở bản ZIP desktop đã đóng gói

1. Giải nén ZIP vào `C:\agent-projects\`. Kiểm tra đường dẫn cuối là `C:\agent-projects\study-planning-agent\start.cmd`.
2. Mở **start.cmd**. Giữ cửa sổ dòng lệnh mở khi dùng ứng dụng. Không cần cài Python, chạy pip, đăng nhập hay kết nối mạng.
3. Mở **Giờ rảnh & giới hạn**. Mỗi dòng tương ứng một ngày trong tuần. Ví dụ `08:00-10:00, 19:00-20:30`. Để trống ngày không học. Thêm ngày bận riêng bằng định dạng YYYY-MM-DD.
4. Vào **Việc học → Nạp ví dụ** để thử với ba việc PDE và Hệ thống phân tán, các hạn được tính từ ngày nhập. Để tự nhập từ đầu, chọn **Môn học → Thêm môn**, rồi **Việc học → Thêm việc**.
5. Chọn **Lịch học** để xem giờ bắt đầu, kết thúc và lý do. Kéo thanh ngang để xem hết cột. **Cảnh báo** liệt kê các hạn trùng ngày và phần việc chưa xếp được.

## Một lần sử dụng từ đầu đến cuối

Tạo việc “Ôn phương trình đặc trưng”, dự kiến 90 phút, ưu tiên 4, độ khó 3. Sau khi lưu, lấy ID ở cột đầu của thẻ Việc học. Tạo việc “Luyện đề PDE” và điền ID vừa lấy vào ô tiên quyết. Lịch sẽ xếp đủ thời gian ôn trước khi xếp buổi luyện đề. Với trần 40 phút mỗi buổi, 90 phút thường tách thành 40 + 40 + 10 phút.

- **Đang trong buổi học** — chọn buổi, bấm **Ghi kết quả**. Ví dụ sau 30 phút, mày thấy vẫn cần 75 phút để hoàn tất. Nhập thực học 30 và còn lại 75. Agent sẽ xếp tiếp 75 phút. Đặt còn lại bằng 0 để hoàn thành việc.
- **Học sớm hoặc học ngoài lịch** — chọn việc ở thẻ Việc học rồi bấm **Ghi tự học**.
- **Bận đột xuất** — chọn buổi, bấm **Bỏ buổi**. Khoảng thời gian đã bỏ được loại khỏi lịch mới. Nếu bận cả ngày, thêm ngày đó vào danh sách ngày bận.
- **Quên ghi kết quả** — buổi hết giờ chuyển vào Nhật ký với trạng thái “Chưa ghi nhận”. Agent giữ nguyên khối lượng chưa xác nhận và xếp lại. Nếu đã học, chọn dòng trong nhật ký rồi bấm **Bổ sung buổi chưa ghi**. Nhập số phút còn lại theo đánh giá hiện tại.
- **Đổi hạn hoặc ước lượng** — chọn **Việc học → Sửa việc**. “Dự kiến ban đầu” phục vụ đối chiếu. “Khối lượng còn lại” quyết định số phút được xếp tiếp.
- **Đọc tiến độ** — đầu màn hình hiển thị số việc hoàn thành, tổng phút thực học và số phút còn lại. Nhật ký lưu các kết quả kể cả khi việc bị xóa.

## Cách Agent quyết định

Lịch sử dụng giờ địa phương của máy và xét 90 ngày kể từ hôm nay. Mặc định mỗi ngày tối đa 120 phút tập trung, mỗi buổi tối đa 40 phút, cách hai buổi ít nhất 10 phút. Ngày không có khung rảnh sẽ trống. Một buổi đang diễn ra thường được giữ khi làm mới. Thay đổi giới hạn nhắm tới các buổi tiếp theo.

Agent duyệt quan hệ tiên quyết, chuyển hạn sớm của việc phụ thuộc cho các bước cần làm trước. Trong các việc có thể bắt đầu, Agent chọn việc có **hạn hiệu lực trừ số phút còn lại** sớm nhất. Khi bằng nhau, nó chọn ưu tiên cao hơn, rồi độ khó cao hơn, cuối cùng dùng ID để kết quả ổn định. Sau mỗi buổi giả định hoàn tất, Agent xét lại các việc đã đủ điều kiện. Việc được xếp trong tương lai chỉ là dự báo. Tiến độ thực tế thay đổi khi người dùng xác nhận.

Đây là thuật toán tham lam. Cảnh báo thiếu thời gian cho biết lịch vừa tạo còn thiếu bao nhiêu phút, không chứng minh mọi cách sắp xếp đều thất bại. Việc đã quá hạn vẫn xuất hiện trong danh sách để người dùng đổi hạn hoặc ghi kết quả. Agent tính lại khi mở ứng dụng, khi lưu thay đổi và mỗi phút trong lúc mở.

## Nhập dữ liệu

**Việc học → Nhập JSON** đọc tệp UTF-8. Dùng `sample.json` làm mẫu. Khai báo tên môn trong `courses`. Mỗi việc trong `tasks` cần ID riêng, tên, môn, loại, số phút ước lượng, độ khó và ưu tiên từ 1 đến 5. Các loại hợp lệ là `Bài tập`, `Kỳ thi` và `Mục tiêu`. Trường `deps` liệt kê ID các việc tiên quyết. Dùng `"due": "2026-12-01 20:30"` cho hạn cố định hoặc `"days": 7` cho hạn sau bảy ngày lúc 22 giờ. Khi ID trùng, hạn sai hoặc phụ thuộc vòng, toàn bộ lần nhập được hoàn tác.

## Mã nguồn, dữ liệu và kiểm thử

| Thành phần | Vai trò |
|---|---|
| app.py | Giao diện Tk, nhập liệu và ghi tiến độ |
| planner.py | Kiểm tra dữ liệu, lập lịch và lưu bằng giao dịch SQLite |
| defaults.json | Khung giờ và giới hạn ban đầu |
| sample.json | Bộ môn và việc mẫu có quan hệ tiên quyết |
| data/study.sqlite3 | Dữ liệu cá nhân, tự tạo khi mở lần đầu |
| runtime/ | Python riêng trong bản ZIP desktop |
| api.py, requirements.txt | HTTP API và các gói Python cần cài |
| test_api.py, test_planner.py, TEST_RESULTS.txt | Kiểm thử HTTP, desktop, thuật toán và kết quả trên Windows |

Để sao lưu, đóng ứng dụng rồi sao chép cả thư mục dự án. Khi chuyển sang máy Windows x64 khác, mở lại start.cmd trong thư mục đã sao chép. Dùng một cửa sổ ứng dụng khi chỉnh sửa cùng một bộ dữ liệu.

Chạy kiểm thử trong PowerShell tại thư mục dự án:

```powershell
.\.venv\Scripts\python.exe -B -m unittest -v
```

Bộ kiểm thử khởi tạo dữ liệu tạm riêng và thực sự tạo cửa sổ Tk ẩn để kiểm tra giao diện nạp mẫu. Để chạy từ mã nguồn bằng Python có sẵn, dùng Python 3.10+ có Tkinter và SQLite, sau đó chạy `python -B app.py`.

