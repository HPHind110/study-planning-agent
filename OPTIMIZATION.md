# Bộ lập lịch nhiều ứng viên

Mỗi lần cập nhật dùng một thời điểm giờ máy, làm tròn xuống phút. Store xử lý buổi hết hạn một lần, áp dụng thay đổi, rồi ghi lịch thắng trong cùng giao dịch SQLite. Các phép thử lịch dùng chung đầu vào chỉ đọc và bộ đếm khối lượng riêng. Xem trước import dùng bản sao trong RAM. Không thay đổi schema SQLite, định dạng backup hay hợp đồng gọi Provider.

## Các lịch được xét

- Baseline giữ nguyên quy tắc V2: truyền hạn sớm ngược qua DAG, xếp theo số phút lịch còn lại trừ khối lượng nhân hệ số quỹ giờ ngày. Hạn cứng, ưu tiên và độ khó chỉ phá hòa ở bước xếp hạng này.
- Lịch tương lai hiện tại được kiểm tra lại dưới các ràng buộc mới. Buổi đang diễn ra được cố định khi còn hợp lệ. Nếu một phần lịch cũ sai, thử giữ các buổi còn hợp lệ theo thứ tự rồi lấp khoảng trống.
- EDF dùng hạn hiệu lực sớm nhất. Ước lượng độ dư dùng tọa độ phút học tích lũy trong các khung rảnh sau khi xét sự kiện, trần ngày và nghỉ. Chiến lược chuỗi xét hạn của từng hậu duệ, khối lượng còn lại của nó và tập tiên quyết chưa xong, cùng ưu tiên cao nhất mà việc đang mở khóa. Chiến lược hạn cứng xét cả hậu duệ có hạn cứng.
- Sửa cục bộ thử tối đa hai vòng. Mỗi vòng đưa tối đa bốn chuỗi còn thiếu lên trước, lấp khoảng trống và thử dời tối đa ba việc cạnh tranh cùng các hậu duệ của chúng. Nếu điểm không tốt hơn, kết thúc. Không đặt thời lượng tối thiểu cho buổi.
- Ngân sách tìm kiếm mặc định ba giây tính từ khi bắt đầu lập lịch. Baseline, kiểm tra lịch hiện tại, xác minh và tính thống kê là phần bắt buộc. Đồng hồ giới hạn các vòng tùy chọn; tổng thời gian có thể vượt ngân sách trên đầu vào rất lớn. Khi hết giờ dùng kết quả hợp lệ tốt nhất đã xét. Luồng duyệt cố định, không ngẫu nhiên; dưới tải máy nặng, số ứng viên kịp xét trước thời hạn có thể khác.

## So sánh và kiểm tra

Tối thiểu hóa lần lượt, bằng nhau mới xét mục kế tiếp:

1. Tổng phút thiếu của việc hạn cứng, rồi số việc hạn cứng chưa xong.
2. Tổng `priority × phút thiếu` của tất cả việc. Sau đó tổng phút thiếu, số việc thiếu, tổng phút của các việc bị chặn bởi tiên quyết chưa xếp xong. Mỗi việc chỉ đóng góp một lần vào tổng này.
3. Riêng sau khi một hạn đã được sửa so với lần lập lịch trước, tính số lần hai buổi liên tiếp đảo thứ tự hạn hiệu lực để ưu tiên đáp ứng thay đổi người dùng vừa nhập.
4. Số buổi thay đổi trong hôm nay và ngày mai, rồi toàn kỳ. Phép đo là hiệu đối xứng các bộ (ID việc, bắt đầu, kết thúc); dời một buổi có thể tính hai thay đổi.
5. Số buổi dưới 20 phút, tổng số buổi và số lần đổi việc giữa hai buổi liên tiếp. Cùng điểm giữ ứng viên được xét trước. ID phá hòa giữa các việc.

Mẫu validator duyệt độc lập các buổi theo thứ tự, trừ phút dự báo khỏi phần thực tế còn lại, kiểm tra ngày bắt đầu, hạn gốc, DAG, sự kiện, giờ rảnh, trần ngày, thời lượng, nghỉ, kỳ lập lịch và buổi đang chạy. Cả hai loại hạn đều không cho phép xếp muộn; phút học dự kiến đúng hạn bằng tổng phút xếp hợp lệ. Việc quá hạn chưa hoàn thành vẫn được giữ.

## Diễn giải kết quả

`GET /dashboard` trả `analysis.optimization` gồm điểm baseline/selected, evaluated, rejected (lý do loại), strategy, timeout, seconds, phút thiếu trực tiếp, phút bị chặn không trùng và impacts theo tiên quyết. Các impacts khác nhau có thể cùng trỏ tới một hậu duệ. Không cộng các dòng impacts. Mục **Phân tích tải** trình bày các số này cùng bảng ngày còn dư và các khoảng có chứng cứ thiếu quỹ giờ.

Trần phút một ngày là giới hạn danh nghĩa. Capacity là ước lượng cho công việc chia nhỏ linh hoạt; số phút thực dùng còn phụ thuộc ngày cho phép, tiên quyết và lựa chọn lịch. Chẩn đoán ngày trống đếm tình trạng các việc còn lại cuối ngày. Đây không phải phép chứng minh mọi cách xếp khác đều bỏ trống ngày đó.

Để chứng minh thiếu giờ trong một khoảng, cộng các khối lượng bắt buộc nằm trọn trong khoảng theo ngày bắt đầu/hạn, rồi so với **cận trên** từ giờ rảnh và trần từng ngày, bỏ qua cạnh tranh và nghỉ. Nếu đang học dở, phép tính nới cận để tránh kết luận sai. Chỉ tiền tố hạn và một tập giới hạn các khoảng quanh việc còn thiếu được xét. Khi chưa có chứng cứ, mức thiếu là kết quả tìm kiếm hữu hạn.

## Chạy lại thử nghiệm

```powershell
.\.venv\Scripts\python -B -m unittest -v
.\.venv\Scripts\python -B benchmark_scheduling.py --backup "C:\path\study-backup.json" --at "2031-03-03 08:00"
.\.venv\Scripts\python -B benchmark_generalization.py
```

Thay đường dẫn và thời điểm bằng tệp riêng và mốc cần so sánh. Benchmark dùng nguyên cấu hình cho cặp baseline/optimized; mỗi biến thể thay hạn hoặc gỡ ngày bắt đầu là một bài toán riêng trong RAM. Có thể dùng `--database` thay `--backup` để mở SQLite chỉ đọc. Bộ kiểm tra giữ lại dùng seed 101–124, 7–85 việc và kỳ 4–35 ngày, độc lập các ví dụ nhỏ dùng phát triển. Không cần thay bộ lập lịch khi đổi kế hoạch.

