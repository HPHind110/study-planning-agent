# Sổ học

Dashboard web, ứng dụng desktop tiếng Việt và HTTP API lập lịch tự học theo hạn, khối lượng và quỹ giờ cá nhân. Cả ba dùng chung thuật toán và cơ sở dữ liệu SQLite trong thư mục dự án.

## Chạy từ GitHub trên Windows

Cài Python 3.13 x64 có Python Launcher, Tkinter và pip. Trong PowerShell:

```powershell
git clone --branch feature/scheduling-optimization https://github.com/HPHind110/study-planning-agent.git
cd study-planning-agent
.\start-api.cmd
```

Từ thư mục dự án, **một lệnh `.\start-api.cmd`** chạy cả dashboard và API. Mở **http://127.0.0.1:8102/** để dùng dashboard hoặc http://127.0.0.1:8102/docs để thử API. Lần đầu, launcher tạo `.venv` trong dự án và tải các gói Python. Sau bước này dashboard chạy offline, tải CSS và JavaScript từ localhost. Dùng Ctrl+C để dừng. Giao diện desktop vẫn chạy riêng bằng `.\start.cmd`. Khi chuyển từ bản ZIP sang bản clone, đóng ứng dụng cũ rồi sao chép thư mục `data` sang bản mới trước lần chạy đầu.

Quy tắc chọn lịch, chẩn đoán và benchmark nằm trong [OPTIMIZATION.md](OPTIMIZATION.md).

## Cập nhật bản Windows đang dùng

Đóng cửa sổ desktop và dừng Uvicorn bằng Ctrl+C. Trong bản cài đã giải nén hoặc chép tay, dùng PowerShell dưới đây để cập nhật mã từ nhánh tính năng. Lệnh giải nén các file đã commit vào thư mục ứng dụng. SQLite, bản sao lưu và môi trường Python nằm ngoài gói mã nguồn.

```powershell
$appDir = 'C:\agent-projects\study-planning-agent'
$stage = Join-Path $env:TEMP ([guid]::NewGuid().ToString())
git clone --single-branch --branch feature/scheduling-optimization https://github.com/HPHind110/study-planning-agent.git $stage
if ($LASTEXITCODE) { throw 'Clone failed' }
$zip = Join-Path $stage 'upgrade.zip'
git -C $stage archive --format=zip -o $zip HEAD
if ($LASTEXITCODE) { throw 'Archive failed' }
Expand-Archive -LiteralPath $zip -DestinationPath $appDir -Force -ErrorAction Stop
Set-Location $appDir
.\start-api.cmd
```

Nếu thư mục cài là một Git clone, dùng `git fetch origin`, `git switch feature/scheduling-optimization`, `git pull --ff-only`, rồi chạy cùng lệnh khởi động.

## Dùng dashboard

1. Vào **Môn học → Thêm môn** hoặc dùng **Thêm việc** rồi nhập tên môn mới. Mỗi việc có hạn, số phút dự kiến, ưu tiên, độ khó và các việc tiên quyết.
2. Trong **Giờ rảnh & giới hạn**, đặt giờ học cho từng ngày, ngày bận, trần phút học và thời gian nghỉ. Lưu để Agent tính lại lịch.
3. Ở **Tổng quan**, chọn ngày trong lịch tuần để xem các buổi. Dùng mũi tên đổi tuần hoặc **Hôm nay** để quay lại. **Xem buổi** hiển thị lý do xếp lịch và cho phép bỏ buổi. **Tạo lịch / Xếp lại lịch** gọi bộ lập lịch thật. Khi sửa việc hoặc ghi kết quả, lịch cũng tự cập nhật.
4. Chọn **Việc học → Chi tiết → Ghi tiến độ**, nhập phút thực học và ước lượng còn lại. Nhập 0 cho phần còn lại để hoàn thành. Dùng bộ lọc để xem việc hoàn thành và **Nhật ký** để đối chiếu thời gian thực học.
5. Dashboard hiển thị hạn sắp tới, việc quá hạn, số phút chưa xếp được và khối lượng còn lại theo môn. Khi đang mở, trang làm mới mỗi phút, tạm dừng lúc đang điền biểu mẫu.

Hướng dẫn payload, mã phản hồi và ví dụ PowerShell nằm trong [API.md](API.md). Schema máy đọc được tại `GET /openapi.json`.

### Lập kế hoạch học kỳ

Trong **Thêm việc**, nhập thời điểm có thể bắt đầu, chọn hạn cứng cho hạn nộp chính thức hoặc hạn mềm cho mốc nội bộ. Thêm ghi chú và chọn việc tiên quyết. Ví dụ, đặt buổi thuyết trình ngày 14/12 vào **Lịch cố định**, rồi đặt việc sửa báo cáo bắt đầu từ 15/12. Việc đã lên lịch cho tương lai vẫn cần được xác nhận bằng tiến độ thực tế.

Trong **Lịch cố định**, đặt ngày kết thúc kỳ lập lịch, giới hạn phút cho từng thứ và các ngoại lệ. Muốn tăng giờ sau khi hết học trên lớp, chọn khoảng 02/01–10/01 rồi nhập khung mới và giới hạn phút. Thêm lớp hàng tuần có ngày kết thúc lặp. Sự kiện hiển thị trong lịch tuần, chiếm khung giờ và không trừ vào trần phút tự học. Thứ tự áp dụng là lịch tuần → ngoại lệ ngày → loại bỏ ngày nghỉ và thời gian sự kiện. Các sự kiện trùng nhau chỉ chặn thời gian một lần.

**Phân tích tải** cho biết lượng đã xếp và chưa xếp, rủi ro theo việc, nhu cầu và quỹ giờ đến từng hạn, cùng các ngày/tuần dồn hạn. Một ngày có nhiều việc đến hạn vẫn có thể hoàn thành nếu học trước. Cảnh báo tách việc quá hạn, thiếu chỗ trước hạn và phần trì hoãn ngoài kỳ. Mọi đề xuất dời hạn mềm cần người dùng quyết định.

**Nhập / xuất** nhận tệp JSON UTF-8. Chọn thêm mới hoặc thay theo phạm vi, xem danh sách thay đổi rồi xác nhận. Có thể tải cả gói kế hoạch hoặc bản sao đầy đủ có nhật ký. Sau thay thế, bản sao trước thay đổi xuất hiện ở cùng màn hình. Để phục hồi, tải bản sao, chọn **Khôi phục toàn bộ**, bật xác nhận phạm vi rồi xem trước. Xem ví dụ và quy tắc ID trong [API.md](API.md).

### Dữ liệu cũ và giới hạn

Ứng dụng đọc trực tiếp hàng JSON hiện có trong SQLite. Việc cũ được hiểu là hạn cứng, không có ngày bắt đầu và ghi chú. Thiết lập cũ tiếp tục có hiệu lực. Bảng sao lưu chỉ được tạo khi cần. Giao diện desktop cũ vẫn dùng chung bộ lập lịch, giữ các thuộc tính mới khi sửa việc. Dùng web để chỉnh các ràng buộc mới.

Tất cả thời điểm có độ chính xác một phút theo giờ máy. Sự kiện qua đêm chặn cả phần thời gian của ngày hôm sau. Giao diện áp dụng ngoại lệ khoảng ngày bằng cách lưu từng ngày. Lịch là dự báo tham lam, không chứng minh tối ưu. Quỹ phút ước tính giả sử có công việc chia nhỏ sẵn sàng làm; ngày bắt đầu, tiên quyết và hạn cụ thể có thể làm giảm số phút dùng được. Bản sao đầy đủ chứa dữ liệu cá nhân và nên được lưu riêng.

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

Lịch dùng ngày kết thúc đã chọn, mặc định 90 ngày kể từ hôm nay. Mặc định mỗi ngày tối đa 120 phút tập trung, mỗi buổi tối đa 40 phút, cách hai buổi ít nhất 10 phút. Buổi đang diễn ra được giữ nếu còn phù hợp với các ràng buộc mới.

Agent truyền hạn sớm qua các việc tiên quyết và chọn việc có ít thời gian dư nhất sau khi tính khối lượng còn lại. Hệ số khối lượng phụ thuộc quỹ phút của ngày và tối đa bằng 8, giúp việc dài được bắt đầu sớm. Khi bằng điểm, Agent xét hạn cứng, ưu tiên, độ khó rồi ID. Nếu các việc đều chưa đến ngày bắt đầu, Agent tiến tới thời điểm đủ điều kiện tiếp theo. Các lần tính cùng dữ liệu và thời điểm cho cùng lịch.

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

Kiểm thử HTTP khởi chạy Uvicorn trên cổng loopback tạm. Kiểm thử trình duyệt dùng Edge và Node.js 22+ để thao tác với lịch, tạo việc, ghi kết quả, lọc việc hoàn thành và kiểm tra lỗi trên biểu mẫu. Bước trình duyệt được bỏ qua nếu thiếu Edge hoặc Node. Dashboard không cần Node để chạy.

