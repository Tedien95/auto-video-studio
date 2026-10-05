# Bản cloud miễn phí

Ứng dụng chạy trên Streamlit Community Cloud. Vercel giữ trang đuôi vercel.app kết nối tới ứng dụng đó. Không cần bật máy cá nhân, không dùng Cloudflare Tunnel và không cần Supabase.

## Cập nhật GitHub

Đưa nội dung bộ này vào repository Tedien95/auto-video-studio, giữ cấu trúc:

```text
.streamlit/config.toml
.gitignore
packages.txt
backend/app.py
backend/web_app.py
backend/cloud_support.py
backend/cleanup.py
backend/requirements.txt
frontend/index.html
frontend/build.mjs
frontend/vercel.json
```

File config.toml lần này nằm trong .streamlit ở NGOÀI CÙNG repository, vì Community Cloud khởi động từ gốc repository. packages.txt cũng ở ngoài cùng để cài FFmpeg. Không đưa mật khẩu hoặc dữ liệu lên GitHub. Có thể xóa backend/Dockerfile, backend/start.py, backend/voice_clone_worker.py, backend/.streamlit, backend/.dockerignore cũ vì bản này không dùng chúng. Frontend giữ như trước.

## Triển khai Streamlit

1. Mở https://share.streamlit.io/ rồi đăng nhập/kết nối GitHub.
2. Chọn Create app và Deploy an app from GitHub.
3. Repository: Tedien95/auto-video-studio; Branch: main; Main file path: backend/web_app.py.
4. Trong Advanced settings, chọn Python 3.11.
5. Trong Secrets, đặt mật khẩu do bạn chọn:

```toml
APP_PASSWORD = "YOUR_PRIVATE_PASSWORD"
```

6. Deploy và đợi cài thư viện. Sau khi chạy, thử đăng nhập bằng mật khẩu vừa đặt. Mật khẩu này chỉ bảo vệ ứng dụng; không dùng mật khẩu GitHub, Vercel hoặc Supabase.

Địa chỉ backend được cấp có dạng https://YOUR_APP.streamlit.app. File README không bắt buộc ở GitHub.

## Kết nối Vercel

Import repository auto-video-studio. Root Directory: frontend. Framework: Other. Build Command: node build.mjs. Output Directory: dist.

Thêm biến môi trường STUDIO_BACKEND_URL bằng địa chỉ Streamlit thật, ví dụ https://YOUR_APP.streamlit.app, rồi Deploy/Redeploy. Không dùng lại địa chỉ trycloudflare.com của bản chạy trên máy.

Nếu trình duyệt chặn cookie bên thứ ba trong iframe, dùng nút Mở toàn màn hình. Không tắt bảo vệ XSRF để né lỗi. Bản Streamlit công khai cho phép nhúng; máy chủ vẫn kiểm tra mật khẩu trước khi xử lý.

## Chức năng và giới hạn

- Clone giọng tạm tắt; không cài Coqui TTS, PyTorch hoặc CUDA.
- Voice TTS tiếng Việt, dịch SRT, tạo SRT từ văn bản và giọng cảm xúc còn giữ.
- Tải video: tối đa 720p, thời lượng tối đa 5 phút khi nguồn cung cấp thông tin thời lượng, giới hạn file 50 MB. Một số nguồn chặn IP cloud hoặc yêu cầu đăng nhập nên tải không được bảo đảm.
- Render CPU: file nguồn tối đa 50 MB; video tối đa 3 phút; tối đa 5 phút cho audio. Timeout render 5 phút, dùng một luồng. Không có GPU; tính năng gắn cứng subtitle vốn chưa được mã gốc thực hiện nên không hiển thị ô đó.
- Nhận diện giọng nói: chỉ model Whisper tiny trên CPU, video/audio tối đa 3 phút. Lần đầu cần tải model. Độ chính xác thấp hơn model lớn.
- Voice TTS/dịch: tối đa 120 câu, 10.000 ký tự, timeline SRT tối đa 5 phút; giọng cảm xúc tối đa 3.000 ký tự.
- Upload tối đa 50 MB. Chỉ một lượt giao diện/tác vụ xử lý cùng lúc để giảm tải RAM.
- Tự quét mỗi giờ khi ứng dụng đang chạy, xóa phiên không hoạt động hơn 24 giờ. Tác vụ đang chạy có khóa bảo vệ. Chặn tác vụ mới khi dữ liệu phiên vượt 900 MB hoặc đĩa còn dưới 500 MB. Đây là giới hạn trước tác vụ, không phải bảo đảm dung lượng tối đa tuyệt đối.

Community Cloud có thể ngủ và có giới hạn tài nguyên. File tạm có thể mất khi app được khởi động lại; tải kết quả về thiết bị ngay sau khi xử lý. Tự dọn không chạy lúc app ngủ; khi thức sẽ khởi động lại. Chưa triển khai lên tài khoản của bạn, chưa xác minh hiệu năng trên cloud thực tế. Tác vụ nặng vẫn có thể vượt hạn mức; thử file ngắn trước.

## Tài liệu

- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
- https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app/embed-your-app
- https://docs.streamlit.io/deploy/streamlit-community-cloud/status
