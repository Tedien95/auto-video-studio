# AutoVideoTool cloud + Vercel

Đây là bản triển khai từ dự án AutoVideoTool. Trang Vercel nhúng ứng dụng Streamlit chạy trên máy chủ cloud. Máy cá nhân có thể tắt. Trang Vercel không thực hiện render hay chạy mô hình AI.

## Máy chủ ứng dụng

Triển khai thư mục `backend` trên dịch vụ hỗ trợ Docker, HTTPS và WebSocket. Dockerfile mặc định dùng CPU; nhận diện và clone giọng sẽ chậm hơn GPU. Nên bắt đầu với 4 CPU, 8 GB RAM và ít nhất 10 GB đĩa, sau đó đo tải thực tế. Đây là cấu hình ước lượng, không phải bảo đảm hiệu năng. Máy chủ phải duy trì kết nối cho các tác vụ dài.

Biến môi trường:

- `APP_PASSWORD`: mật khẩu truy cập do bạn chọn; bắt buộc. Chỉ đặt ở backend.
- `BACKEND_PUBLIC_URL`: URL HTTPS công khai của backend, đặt sau khi dịch vụ cấp địa chỉ.
- `DATA_ROOT`: mặc định `/data`. Gắn ổ đĩa bền vững tại `/data` để lưu model và dữ liệu phiên.
- `PORT`: dịch vụ thường tự cung cấp, mặc định 8501.

Nếu dịch vụ không gắn được ổ đĩa tại /data cho UID 10001, cấp quyền ghi cho UID đó hoặc đặt DATA_ROOT ở đường dẫn được cấp quyền. Cache model cần quyền ghi tại /data/models.

Chạy Docker trên máy chủ:

```sh
docker build -t autovideotool ./backend
docker run --env-file backend.env -p 8501:8501 -v studio-data:/data autovideotool
```

Tệp backend.env không đưa lên Git:

```text
APP_PASSWORD=YOUR_PRIVATE_PASSWORD
BACKEND_PUBLIC_URL=https://YOUR_BACKEND_DOMAIN
```

Đặt HTTPS qua dịch vụ cloud hoặc reverse proxy có hỗ trợ WebSocket. Cookie upload đã cấu hình cho iframe qua HTTPS. Nếu trình duyệt chặn cookie bên thứ ba, dùng nút Mở toàn màn hình. Một số phiên bản Streamlit cũ không hỗ trợ `xsrfCookieSameSite`: cài phiên bản hỗ trợ theo tài liệu hiện tại; không tắt bảo vệ XSRF để né lỗi.

## Trang Vercel

Đưa bộ mã này vào repository của bạn. Trên Vercel, import repository và chọn:

- Root Directory: `frontend`
- Framework Preset: Other
- Build Command: `node build.mjs`
- Output Directory: `dist`
- Environment Variable: `STUDIO_BACKEND_URL=https://YOUR_BACKEND_DOMAIN`

Deploy. Vercel sẽ cấp URL đuôi vercel.app; tên mong muốn chỉ dùng được nếu còn trống. Nếu dùng CLI, chạy từ thư mục frontend sau khi đăng nhập Vercel:

```sh
vercel --prod
```

Mỗi lần thay backend URL, cập nhật biến môi trường rồi redeploy frontend. Build cố ý báo lỗi khi chưa có URL HTTPS thật để tránh xuất bản một trang không nối được ứng dụng.

## Thay đổi so với bản Windows

- Bỏ cửa sổ chọn thư mục máy tính, thêm nút tải video về thiết bị.
- Tách file tạm và đầu ra theo từng phiên, làm sạch tên file tải lên.
- Dùng Python hiện tại để chạy worker; không dùng voice_clone_env/Scripts/python.exe.
- CPU là mặc định khi render; worker clone tự chọn CUDA nếu có.
- Thay requirements chứa wheel Windows từ ổ F: bằng thư viện portable.
- XTTS-v2 gốc không hỗ trợ tiếng Việt; mục clone bỏ lựa chọn vi. Voice TTS tiếng Việt vẫn giữ.
- Thêm mật khẩu cho ứng dụng cá nhân chạy công khai trên cloud.

## Giới hạn và kiểm tra trước khi sử dụng

Docker chưa được build và ứng dụng chưa được chạy trên cloud. Dependencies có khoảng phiên bản; lần build thành công đầu tiên nên lưu lock file/image digest. Chưa kiểm tra tải video ngoài mạng, TTS, Whisper, model XTTS hay tốc độ render thực tế. CUDA cần image và máy chủ GPU phù hợp; image mặc định cài PyTorch CPU.

Model XTTS cần tải lần đầu; mã gốc tự đặt COQUI_TOS_AGREED. Chỉ sử dụng model theo điều khoản của nhà cung cấp. Tính năng gắn cứng subtitle trong Auto Render hiện chưa được mã gốc nối vào lệnh FFmpeg; bản triển khai giữ giới hạn này.

File của phiên được lưu tại /data/sessions. Dọn phiên cũ theo chính sách lưu trữ của bạn, chỉ khi không còn tác vụ chạy; dữ liệu phiên không tự xóa. Tải file quan trọng về thiết bị trước khi đóng phiên. Chạy một instance ứng dụng; nhiều replica cần session stickiness. Mật khẩu này là cổng truy cập chung, không phải hệ thống tài khoản nhiều người dùng.

## Tài liệu

- https://docs.streamlit.io/deploy/tutorials/docker
- https://docs.streamlit.io/develop/api-reference/configuration/config.toml
- https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app/embed-your-app
- https://vercel.com/docs/cli/deploying-from-cli
- https://huggingface.co/coqui/XTTS-v2
