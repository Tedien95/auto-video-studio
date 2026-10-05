import os
import time
import asyncio
import threading
import subprocess
import streamlit as st
import pysrt
from pydub import AudioSegment
import edge_tts
import yt_dlp
from deep_translator import GoogleTranslator
import sys
import re
import uuid
import hmac
from pathlib import Path
from faster_whisper import WhisperModel
from streamlit_option_menu import option_menu


# Cấu hình giao diện Streamlit
st.set_page_config(
    page_title="Auto Video Studio - All in One",
    page_icon="🎬",
    layout="wide"
)

# Private cloud access; configure APP_PASSWORD on the hosting provider.
access_password = os.environ.get("APP_PASSWORD", "")
if not access_password:
    st.error("Ứng dụng chưa được cấu hình quyền truy cập. Vui lòng đặt APP_PASSWORD trên máy chủ.")
    st.stop()
if not st.session_state.get("authenticated", False):
    st.title("🎬 Auto Video Studio")
    with st.form("access_form"):
        password = st.text_input("Mật khẩu truy cập", type="password")
        submitted = st.form_submit_button("Đăng nhập")
    if submitted:
        if hmac.compare_digest(password.encode(), access_password.encode()):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Mật khẩu chưa đúng.")
    st.stop()

APP_DIR = Path(__file__).resolve().parent
if "workspace_id" not in st.session_state:
    st.session_state.workspace_id = uuid.uuid4().hex
DATA_ROOT = Path(os.environ.get("DATA_ROOT", str(APP_DIR / "data")))
SESSION_DIR = DATA_ROOT / "sessions" / st.session_state.workspace_id
OUTPUT_DIR = SESSION_DIR / "outputs"
TEMP_DIR = SESSION_DIR / "temp_audio"
DOWNLOAD_DIR = SESSION_DIR / "downloads"
for directory in (OUTPUT_DIR, TEMP_DIR, DOWNLOAD_DIR):
    directory.mkdir(parents=True, exist_ok=True)

def safe_filename(name):
    name = re.split(r"[/\\]", name)[-1]
    name = re.sub(r"[^\w. ()-]", "_", name).strip(" .")
    return name[:160] or "file"

# ================= THEME: DARK/LIGHT + GRADIENT + GLASS =================
if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = True

col_title, col_toggle = st.columns([6, 1])
with col_toggle:
    st.session_state.dark_mode = st.toggle("🌙 Dark", value=st.session_state.dark_mode)

is_dark = st.session_state.dark_mode

if is_dark:
    bg_gradient = "linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%)"
    glass_bg = "rgba(255, 255, 255, 0.06)"
    glass_border = "rgba(255, 255, 255, 0.15)"
    text_color = "#f0f0f5"
    accent = "#8a7fff"
else:
    bg_gradient = "linear-gradient(135deg, #e0eafc 0%, #cfdef3 50%, #f5f7fa 100%)"
    glass_bg = "rgba(255, 255, 255, 0.55)"
    glass_border = "rgba(255, 255, 255, 0.8)"
    text_color = "#1a1a2e"
    accent = "#5b6ee1"

st.markdown(f"""
<style>
    .stApp {{
        background: {bg_gradient};
        background-attachment: fixed;
        color: {text_color};
    }}
    [data-testid="stAppViewContainer"] > .main {{
        background: transparent;
    }}
    [data-testid="stVerticalBlock"] > [data-testid="stVerticalBlock"] {{
        background: {glass_bg};
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border-radius: 16px;
        border: 1px solid {glass_border};
    }}
    .stButton > button {{
        background: linear-gradient(135deg, {accent}, #ff6ec4);
        color: white;
        border: none;
        border-radius: 10px;
        font-weight: 600;
        transition: all 0.2s ease;
    }}
    .stButton > button:hover {{
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(0,0,0,0.25);
    }}
    div[data-baseweb="select"] > div, .stTextInput input, .stTextArea textarea {{
        background: {glass_bg} !important;
        backdrop-filter: blur(10px);
        border-radius: 10px !important;
        border: 1px solid {glass_border} !important;
        color: {text_color} !important;
    }}
    h1, h2, h3, p, label, .stMarkdown {{
        color: {text_color} !important;
    }}
</style>
""", unsafe_allow_html=True)

# Tạo các thư mục lưu trữ nếu chưa có


TAG_PRESETS = {
    # tag (viết thường, không dấu ngoặc) : (rate_delta, pitch_delta)
    "laughing": (25, 30),
    "laughs": (25, 30),
    "cười": (25, 30),
    "whispers": (-25, -10),
    "whispering": (-25, -10),
    "thì thầm": (-25, -10),
    "shouting": (15, 25),
    "yelling": (15, 25),
    "hét lên": (15, 25),
    "sighs": (-15, -15),
    "sighing": (-15, -15),
    "thở dài": (-15, -15),
    "breathing hard": (20, 15),
    "out of breath": (20, 15),
    "thở gấp": (20, 15),
    "sad": (-20, -20),
    "crying": (-20, -20),
    "buồn": (-20, -20),
    "excited": (15, 20),
    "hào hứng": (15, 20),
    "angry": (10, 15),
    "tức giận": (10, 15),
    "calm": (-10, -5),
    "softly": (-10, -5),
    "nhẹ nhàng": (-10, -5),
}

def parse_emotion_text(text):
    """Tách văn bản thành list (đoạn_text, rate_delta, pitch_delta) dựa theo tag [tag] trong ngoặc vuông."""
    import re
    parts = re.split(r'(\[[^\]]+\])', text)
    segments = []
    current_rate_delta, current_pitch_delta = 0, 0
    unknown_tags = set()

    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.startswith("[") and part.endswith("]"):
            tag_name = part[1:-1].strip().lower()
            if tag_name in TAG_PRESETS:
                current_rate_delta, current_pitch_delta = TAG_PRESETS[tag_name]
            else:
                unknown_tags.add(tag_name)
                current_rate_delta, current_pitch_delta = 0, 0
        else:
            segments.append((part, current_rate_delta, current_pitch_delta))

    return segments, unknown_tags

# Danh sách giọng đọc phổ biến của Edge TTS
VOICE_OPTIONS = {
    "Nữ - Hoài Mỹ (Ngọc Huyền) [vi-VN-HoaiMyNeural]": "vi-VN-HoaiMyNeural",
    "Nam - Nam Minh [vi-VN-NamMinhNeural]": "vi-VN-NamMinhNeural",
    "Nữ - Xiaoxiao (Tiếng Trung) [zh-CN-XiaoxiaoNeural]": "zh-CN-XiaoxiaoNeural",
    "Nam - Yunxi (Tiếng Trung) [zh-CN-YunxiNeural]": "zh-CN-YunxiNeural",
    "Nữ - Jenny (Tiếng Anh) [en-US-JennyNeural]": "en-US-JennyNeural",
    "Nam - Guy (Tiếng Anh) [en-US-GuyNeural]": "en-US-GuyNeural",
    "Nữ - Nanami (Tiếng Nhật) [ja-JP-NanamiNeural]": "ja-JP-NanamiNeural",
    "Nam - Keita (Tiếng Nhật) [ja-JP-KeitaNeural]": "ja-JP-KeitaNeural",
    "Nữ - SunHi (Tiếng Hàn) [ko-KR-SunHiNeural]": "ko-KR-SunHiNeural",
    "Nam - InJoon (Tiếng Hàn) [ko-KR-InJoonNeural]": "ko-KR-InJoonNeural",
    "Nữ - Denise (Tiếng Pháp) [fr-FR-DeniseNeural]": "fr-FR-DeniseNeural",
    "Nam - Henri (Tiếng Pháp) [fr-FR-HenriNeural]": "fr-FR-HenriNeural",
    "Nữ - Katja (Tiếng Đức) [de-DE-KatjaNeural]": "de-DE-KatjaNeural",
    "Nam - Conrad (Tiếng Đức) [de-DE-ConradNeural]": "de-DE-ConradNeural",
    "Nữ - Elvira (Tiếng Tây Ban Nha) [es-ES-ElviraNeural]": "es-ES-ElviraNeural",
    "Nam - Alvaro (Tiếng Tây Ban Nha) [es-ES-AlvaroNeural]": "es-ES-AlvaroNeural",
    "Nữ - Elena (Tiếng Ý) [it-IT-ElsaNeural]": "it-IT-ElsaNeural",
    "Nam - Diego (Tiếng Ý) [it-IT-DiegoNeural]": "it-IT-DiegoNeural",
    "Nữ - Yaoyao (Tiếng Thái) [th-TH-PremwadeeNeural]": "th-TH-PremwadeeNeural",
    "Nam - Niwat (Tiếng Thái) [th-TH-NiwatNeural]": "th-TH-NiwatNeural",
}
def format_srt_time(seconds):
    ms = int(round((seconds - int(seconds)) * 1000))
    s = int(seconds) % 60
    m = (int(seconds) // 60) % 60
    h = int(seconds) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

@st.cache_resource
def load_whisper_model(model_size):
    try:
        return WhisperModel(model_size, device="cuda", compute_type="float16")
    except Exception:
        return WhisperModel(model_size, device="cpu", compute_type="int8")

# --- Luồng nền + event loop DUY NHẤT, dùng chung xuyên suốt cả phiên chạy app ---
_tts_loop = None
_tts_thread = None
_tts_loop_lock = threading.Lock()

def _get_tts_loop():
    global _tts_loop, _tts_thread
    with _tts_loop_lock:
        if _tts_loop is None:
            _tts_loop = asyncio.new_event_loop()
            _tts_thread = threading.Thread(target=_tts_loop.run_forever, daemon=True)
            _tts_thread.start()
    return _tts_loop

def generate_single_tts(text, voice, rate, pitch, output_file):
    loop = _get_tts_loop()

    async def _do():
        comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        await comm.save(output_file)

    future = asyncio.run_coroutine_threadsafe(_do(), loop)
    future.result(timeout=60)  # chờ tối đa 60s cho 1 câu

# Tiêu đề giao diện
st.title("🎬 Studio Tự Động Hóa Video & Subtitle (Cá nhân)")
st.caption("Công cụ tự động: Tải video không watermark | Dịch SRT | Đọc Voice AI khớp Timeline | Auto Render")

# Tạo 5 Tab chức năng
selected = option_menu(
    menu_title=None,
    options=["Tải Video", "Voice TTS", "Dịch SRT", "Auto Render", "Tạo SRT", "Nhân Bản Giọng", "Văn Bản Cảm Xúc"],
    icons=["cloud-arrow-down", "mic", "translate", "camera-reels", "file-earmark-text", "person-voice", "emoji-laughing"],
    orientation="horizontal",
    default_index=0,
    styles={
        "container": {
            "padding": "8px",
            "background": glass_bg,
            "backdrop-filter": "blur(16px)",
            "border-radius": "16px",
            "border": f"1px solid {glass_border}",
        },
        "icon": {"color": accent, "font-size": "18px"},
        "nav-link": {
            "font-size": "15px",
            "font-weight": "600",
            "color": text_color,
            "border-radius": "10px",
            "margin": "2px",
        },
        "nav-link-selected": {
            "background": f"linear-gradient(135deg, {accent}, #ff6ec4)",
            "color": "white",
        },
    }
)

# ================= TAB 1: TẢI VIDEO =================
if selected == "Tải Video":
    st.subheader("Tải Video Không Watermark (TikTok, Douyin, YouTube, Bilibili...)")
    url_input = st.text_input("Dán link video cần tải:", placeholder="https://www.tiktok.com/... hoặc https://v.douyin.com/...")
        # Lưu đường dẫn thư mục tải về vào session_state để không bị mất khi rerun
    if "download_folder" not in st.session_state:
        st.session_state.download_folder = str(DOWNLOAD_DIR)
    
    custom_filename = st.text_input(
        "Đặt tên file (để trống = giữ tên gốc video):", value="", key="custom_filename"
    )
    st.caption("Sau khi xử lý, nhấn Tải file để lưu về thiết bị của bạn.")
    VIDEO_QUALITY = {
        "Tốt nhất (Best - nặng, lâu nhất)": "bestvideo+bestaudio/best",
        "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "720p (khuyên dùng - nhanh)": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "480p (nhanh nhất)": "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
    }
    AUDIO_QUALITY = {
        "320 kbps (cao nhất)": "320",
        "192 kbps (khuyên dùng)": "192",
        "128 kbps (nhẹ)": "128",
    }
    
    col_dl1, col_dl2, col_dl3, col_dl4 = st.columns(4)
    with col_dl1:
        download_type = st.radio("Loại tải:", ["🎬 Video", "🎵 Chỉ Audio (MP3)"], horizontal=True)
    
    is_audio_only = download_type == "🎵 Chỉ Audio (MP3)"
    
    with col_dl2:
        if is_audio_only:
            selected_audio_label = st.selectbox("Chất lượng Audio:", list(AUDIO_QUALITY.keys()), index=1)
        else:
            selected_video_label = st.selectbox("Chất lượng Video:", list(VIDEO_QUALITY.keys()), index=2)
    with col_dl3:
        get_thumbnail = st.checkbox("Tải kèm Thumbnail", value=True, disabled=is_audio_only)
    with col_dl4:
        output_format = st.selectbox(
            "Định dạng file xuất:",
            ["mp4", "mkv", "webm"],
            index=0,
            disabled=is_audio_only,
            help="Chỉ áp dụng cho Video. Audio luôn xuất MP3."
        )
    
    dl_progress_bar = st.empty()
    dl_status_text = st.empty()
    
    if st.button("🚀 Bắt đầu tải Video", key="btn_download"):
        if not url_input.strip():
            st.warning("Vui lòng nhập đường link hợp lệ!")
        else:
            progress_bar_widget = dl_progress_bar.progress(0)

            def progress_hook(d):
                if d['status'] == 'downloading':
                    total = d.get('total_bytes') or d.get('total_bytes_estimate')
                    downloaded = d.get('downloaded_bytes', 0)
                    speed = d.get('speed')
                    speed_str = f"{speed/1024/1024:.2f} MB/s" if speed else "..."
                    if total:
                        percent = downloaded / total
                        progress_bar_widget.progress(min(percent, 1.0))
                        dl_status_text.text(
                            f"Đang tải: {downloaded/1024/1024:.1f}MB / {total/1024/1024:.1f}MB "
                            f"({percent*100:.0f}%) - Tốc độ: {speed_str}"
                        )
                    else:
                        dl_status_text.text(f"Đang tải: {downloaded/1024/1024:.1f}MB - Tốc độ: {speed_str}")
                elif d['status'] == 'finished':
                    dl_status_text.text("Đã tải xong, đang xử lý/ghép file...")

            try:
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'noplaylist': True,
                    'progress_hooks': [progress_hook],
                }

                if is_audio_only:
                    ydl_opts['format'] = 'bestaudio/best'
                    ydl_opts['postprocessors'] = [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': AUDIO_QUALITY[selected_audio_label],
                    }]
                else:
                    ydl_opts['format'] = VIDEO_QUALITY[selected_video_label]
                    ydl_opts['writethumbnail'] = get_thumbnail
                    ydl_opts['merge_output_format'] = output_format

                # Xác định tên file - nằm CÙNG CẤP với if/else phía trên, không lồng vào else
                if custom_filename.strip():
                    filename_template = f"{safe_filename(custom_filename.strip())}.%(ext)s"
                else:
                    suffix = "Audio" if is_audio_only else selected_video_label.split(" ")[0]
                    filename_template = f"%(title)s [{suffix}].%(ext)s"

                ydl_opts['outtmpl'] = os.path.join(st.session_state.download_folder, filename_template)

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url_input, download=True)
                    filename = ydl.prepare_filename(info)
                    if is_audio_only:
                        filename = os.path.splitext(filename)[0] + ".mp3"

                dl_progress_bar.empty()
                dl_status_text.empty()
                st.success(f"✅ Đã tải thành công: **{os.path.basename(filename)}**")

                if not os.path.exists(filename):
                    candidates = sorted(DOWNLOAD_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
                    candidates = [p for p in candidates if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mp3")]
                    if candidates:
                        filename = str(candidates[0])
                if os.path.exists(filename):
                    with open(filename, "rb") as downloaded_file:
                        st.download_button("💾 Tải file về máy", downloaded_file.read(), file_name=os.path.basename(filename))
                    if is_audio_only:
                        st.audio(filename)
                    else:
                        st.video(filename)
            except Exception as e:
                dl_progress_bar.empty()
                dl_status_text.empty()
                st.error(f"Lỗi khi tải video: {e}")

# ================= TAB 2: VOICE TTS KHỚP TIMELINE =================
if selected == "Voice TTS":
    st.subheader("Chuyển File .SRT Thành Giọng Đọc Khớp Chính Xác Timeline")
    
    col_v1, col_v2 = st.columns(2)
    with col_v1:
        srt_file = st.file_uploader("Chọn hoặc kéo thả file .SRT vào đây:", type=["srt"], key="srt_uploader_tts")
    with col_v2:
        selected_voice_label = st.selectbox("Chọn Giọng Đọc:", list(VOICE_OPTIONS.keys()))
        selected_voice = VOICE_OPTIONS[selected_voice_label]
        
        speed = st.slider("Tốc độ đọc (%):", min_value=-50, max_value=100, value=0, step=5)
        pitch = st.slider("Cao độ (%):", min_value=-50, max_value=50, value=0, step=5)
        
        rate_str = f"{speed:+d}%"
        pitch_str = f"{pitch:+d}Hz"

    if st.button("🎙️ Tạo Audio Khớp Timeline (.WAV)", key="btn_generate_tts"):
        if not srt_file:
            st.warning("Vui lòng tải lên 1 file .SRT!")
        else:
            # Lưu tạm file srt
            temp_srt_path = f"{OUTPUT_DIR.as_posix()}/temp_sub.srt"
            with open(temp_srt_path, "wb") as f:
                f.write(srt_file.read())
            
            output_wav_name = f"outputs/Voice_{int(time.time())}.wav"
            
            try:
                subs = pysrt.open(temp_srt_path, encoding='utf-8')
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                final_audio = AudioSegment.silent(duration=0, frame_rate=24000)
                current_time_ms = 0
                total_lines = len(subs)

                for idx, sub in enumerate(subs):
                    status_text.text(f"Đang tạo giọng đọc câu {idx+1}/{total_lines}: {sub.text[:30]}...")
                    start_ms = (sub.start.hours * 3600 + sub.start.minutes * 60 + sub.start.seconds) * 1000 + sub.start.milliseconds
                    
                    temp_seg_file = f"temp_audio/seg_{idx}.mp3"
                    text_clean = sub.text.replace("\n", " ").strip()
                    
                    if text_clean:
                        seg_audio = None
                        # Thử tối đa 3 lần, có chờ giữa các lần nếu bị lỗi (rate-limit từ server TTS)
                        for attempt in range(3):
                            try:
                                if os.path.exists(temp_seg_file):
                                    os.remove(temp_seg_file)
                                generate_single_tts(text_clean, selected_voice, rate_str, pitch_str, temp_seg_file)
                                if os.path.exists(temp_seg_file) and os.path.getsize(temp_seg_file) > 100:
                                    seg_audio = AudioSegment.from_file(temp_seg_file)
                                    # Chuẩn hóa: cùng sample rate/kênh/độ sâu bit -> tránh rè/méo/robot khi ghép nối
                                    seg_audio = seg_audio.set_frame_rate(24000).set_channels(1).set_sample_width(2)
                                    break
                            except Exception:
                                seg_audio = None
                            time.sleep(1.0 * (attempt + 1))
                        
                        time.sleep(0.15)  # nghỉ nhẹ giữa các câu để tránh bị giới hạn tốc độ
                        
                        if seg_audio is None:
                            st.warning(f"⚠️ Bỏ qua câu {idx+1} (không tạo được giọng đọc): \"{text_clean[:40]}...\"")
                        else:
                            if start_ms > current_time_ms:
                                silence_gap = start_ms - current_time_ms
                                final_audio += AudioSegment.silent(duration=silence_gap, frame_rate=24000)
                                current_time_ms = start_ms
                            
                            final_audio += seg_audio
                            current_time_ms += len(seg_audio)
                        
                        if os.path.exists(temp_seg_file):
                            os.remove(temp_seg_file)
                    
                    progress_bar.progress((idx + 1) / total_lines)

                final_audio.export(output_wav_name, format="wav")
                status_text.empty()
                progress_bar.empty()
                
                st.success(f"🎉 Hoàn tất! Đã tạo file Audio khớp timeline thành công!")
                st.audio(output_wav_name, format="audio/wav")
                
                with open(output_wav_name, "rb") as f_wav:
                    st.download_button("💾 Tải file Audio WAV về máy", data=f_wav, file_name=os.path.basename(output_wav_name), mime="audio/wav")
            except Exception as e:
                st.error(f"Lỗi trong quá trình xử lý SRT: {e}")

# ================= TAB 3: DỊCH SUBTITLE =================
if selected == "Dịch SRT":
    st.subheader("Dịch File Phụ Đề (.SRT) Đa Ngôn Ngữ Giữ Nguyên Timeline")
    srt_trans_file = st.file_uploader("Tải file .SRT cần dịch:", type=["srt"], key="srt_uploader_trans")
    
    LANG_NAMES = {
        "auto": "Tự động phát hiện",
        "vi": "Tiếng Việt",
        "en": "Tiếng Anh",
        "zh-CN": "Tiếng Trung (Giản thể)",
        "zh-TW": "Tiếng Trung (Phồn thể)",
        "ja": "Tiếng Nhật",
        "ko": "Tiếng Hàn",
        "fr": "Tiếng Pháp",
        "de": "Tiếng Đức",
        "es": "Tiếng Tây Ban Nha",
        "it": "Tiếng Ý",
        "th": "Tiếng Thái",
        "id": "Tiếng Indonesia",
        "ru": "Tiếng Nga",
        "pt": "Tiếng Bồ Đào Nha",
        "ar": "Tiếng Ả Rập",
        "hi": "Tiếng Hindi",
    }
    
    SOURCE_LANGS = ["auto", "en", "zh-CN", "zh-TW", "ja", "ko", "fr", "de", "es", "it", "th", "id", "ru", "pt", "ar", "hi"]
    TARGET_LANGS = ["vi", "en", "zh-CN", "ja", "ko", "fr", "de", "es", "it", "th", "id", "ru", "pt"]
    
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        source_lang = st.selectbox("Ngôn ngữ gốc:", SOURCE_LANGS, format_func=lambda x: LANG_NAMES.get(x, x))
    with col_t2:
        target_lang = st.selectbox("Dịch sang:", TARGET_LANGS, format_func=lambda x: LANG_NAMES.get(x, x))
    
    if st.button("🌐 Bắt đầu Dịch SRT", key="btn_translate"):
        if not srt_trans_file:
            st.warning("Vui lòng tải lên file .SRT!")
        else:
            with st.spinner("Đang tiến hành dịch từng dòng phụ đề..."):
                try:
                    temp_in_srt = f"{OUTPUT_DIR.as_posix()}/raw_translate.srt"
                    with open(temp_in_srt, "wb") as f:
                        f.write(srt_trans_file.read())
                    
                    subs = pysrt.open(temp_in_srt, encoding='utf-8')
                    translator = GoogleTranslator(source=source_lang, target=target_lang)
                    
                    progress_bar_trans = st.progress(0)
                    status_text_trans = st.empty()
                    total_subs = len(subs)
                    error_count = 0
                    
                    for idx, sub in enumerate(subs):
                        original_text = sub.text.strip()
                        if original_text:
                            translated = None
                            for attempt in range(3):
                                try:
                                    result = translator.translate(original_text)
                                    # Phát hiện trang lỗi Google trả về thay vì bản dịch thật
                                    if result and "Error 500" not in result and "That's an error" not in result and len(result) < len(original_text) * 6:
                                        translated = result
                                        break
                                except Exception:
                                    translated = None
                                time.sleep(1.0 * (attempt + 1))
                            
                            if translated:
                                sub.text = translated
                            else:
                                error_count += 1
                                status_text_trans.text(f"⚠️ Câu {idx+1} dịch lỗi, giữ nguyên bản gốc.")
                            
                            time.sleep(0.3)  # nghỉ giữa các câu để tránh bị chặn
                        
                        progress_bar_trans.progress((idx + 1) / total_subs)
                        status_text_trans.text(f"Đang dịch câu {idx+1}/{total_subs}...")
                    
                    progress_bar_trans.empty()
                    status_text_trans.empty()
                    if error_count > 0:
                        st.warning(f"⚠️ Có {error_count} câu bị lỗi khi dịch, đã giữ nguyên văn bản gốc cho các câu đó.")
                    
                    out_trans_path = f"{OUTPUT_DIR.as_posix()}/Translated_Sub.srt"
                    subs.save(out_trans_path, encoding='utf-8')
                    
                    st.success("✅ Đã dịch thành công file SRT!")
                    with open(out_trans_path, "r", encoding="utf-8") as f_sub:
                        trans_content = f_sub.read()
                        st.text_area("Xem trước nội dung đã dịch:", trans_content[:1500], height=250)
                        st.download_button("💾 Tải File .SRT Đã Dịch", data=trans_content, file_name="Sub_Da_Dich.srt", mime="text/plain")
                except Exception as e:
                    st.error(f"Lỗi khi dịch phụ đề: {e}")

# ================= TAB 4: AUTO RENDER =================
if selected == "Auto Render":
    st.subheader("Ghép Tự Động: Video Gốc + Audio Voice AI + Subtitle")
    st.info("💡 Hỗ trợ render trực tiếp với FFmpeg bằng GPU/CPU tốc độ cao.")
    
    rend_col1, rend_col2 = st.columns(2)
    with rend_col1:
        video_input = st.file_uploader("1. Chọn File Video gốc (.mp4, .mkv):", type=["mp4", "mkv", "mov"])
        audio_input = st.file_uploader("2. Chọn File Audio Voice (.wav, .mp3):", type=["wav", "mp3"])
    with rend_col2:
        sub_input = st.file_uploader("3. (Tùy chọn) Chọn File Subtitle để gắn cứng vào video:", type=["srt"])
        use_gpu = st.checkbox("Sử dụng GPU NVIDIA (NVENC) để render siêu tốc", value=False)
    
    if st.button("🎬 Render Video Ngay", key="btn_render"):
        if not video_input or not audio_input:
            st.warning("Vui lòng tải lên tối thiểu File Video và File Audio!")
        else:
            with st.spinner("Đang tiến hành ghép và render video..."):
                try:
                    # Lưu file tạm
                    vid_path = f"outputs/input_vid_{safe_filename(video_input.name)}"
                    aud_path = f"outputs/input_aud_{safe_filename(audio_input.name)}"
                    out_render_path = f"outputs/Final_Render_{int(time.time())}.mp4"
                    
                    with open(vid_path, "wb") as f: f.write(video_input.read())
                    with open(aud_path, "wb") as f: f.write(audio_input.read())
                    
                    encoder = "h264_nvenc" if use_gpu else "libx264"
                    cmd = [
                        "ffmpeg", "-y",
                        "-i", vid_path,
                        "-i", aud_path,
                        "-c:v", encoder,
                        "-map", "0:v:0",
                        "-map", "1:a:0",
                        "-c:a", "aac",
                        "-b:a", "192k",
                        "-shortest",
                        out_render_path
                    ]
                    
                    subprocess.run(cmd, check=True)
                    st.success("🎉 Render hoàn tất!")
                    st.video(out_render_path)
                    
                    with open(out_render_path, "rb") as f_out:
                        st.download_button("💾 Tải Video Thành Phẩm Về Máy", data=f_out, file_name="Video_Thanh_Pham.mp4", mime="video/mp4")
                except Exception as e:
                    st.error(f"Lỗi khi render video: {e}")

# ================= TAB 5: TẠO FILE SRT =================
if selected == "Tạo SRT":
    st.subheader("📝 Tạo File Phụ Đề (.SRT)")
    
    srt_mode = st.radio(
        "Chọn cách tạo SRT:",
        ["🎧 AI Nhận Diện Giọng Nói (từ Video/Audio)", "✍️ Tự Nhập Văn Bản (tự chia thời gian)"],
        horizontal=True
    )
    
    st.divider()
    
    # ---------- CHẾ ĐỘ 1: AI SPEECH-TO-TEXT ----------
    if srt_mode == "🎧 AI Nhận Diện Giọng Nói (từ Video/Audio)":
        st.caption("Tải lên file Video hoặc Audio, AI sẽ tự nghe và tạo file SRT kèm timestamp.")
        
        media_file = st.file_uploader(
            "Chọn file Video/Audio:",
            type=["mp4", "mkv", "mov", "mp3", "wav", "m4a"],
            key="srt_gen_media_uploader"
        )
        
        col_w1, col_w2 = st.columns(2)
        with col_w1:
            model_size = st.selectbox(
                "Độ chính xác AI (model càng lớn càng chính xác nhưng càng chậm):",
                ["tiny", "base", "small", "medium"],
                index=1
            )
        with col_w2:
            whisper_lang = st.selectbox(
                "Ngôn ngữ trong file:",
                ["auto", "vi", "en", "zh", "ja", "ko", "fr", "de", "es"],
                format_func=lambda x: {
                    "auto": "Tự động phát hiện", "vi": "Tiếng Việt", "en": "Tiếng Anh",
                    "zh": "Tiếng Trung", "ja": "Tiếng Nhật", "ko": "Tiếng Hàn",
                    "fr": "Tiếng Pháp", "de": "Tiếng Đức", "es": "Tiếng Tây Ban Nha"
                }.get(x, x)
            )
        
        if st.button("🚀 Bắt đầu Nhận Diện & Tạo SRT", key="btn_generate_srt_ai"):
            if not media_file:
                st.warning("Vui lòng tải lên 1 file Video hoặc Audio!")
            else:
                temp_media_path = f"temp_audio/srt_source_{int(time.time())}_{safe_filename(media_file.name)}"
                with open(temp_media_path, "wb") as f:
                    f.write(media_file.read())
                
                try:
                    with st.spinner(f"Đang tải model AI ({model_size})... (lần đầu sẽ hơi lâu do tải model)"):
                        model = load_whisper_model(model_size)
                    
                    lang_param = None if whisper_lang == "auto" else whisper_lang
                    segments, info = model.transcribe(temp_media_path, language=lang_param)
                    
                    total_duration = info.duration if info.duration else 1.0
                    progress_bar_srt = st.progress(0)
                    status_text = st.empty()
                    
                    srt_lines = []
                    for idx, seg in enumerate(segments, start=1):
                        srt_lines.append(str(idx))
                        srt_lines.append(f"{format_srt_time(seg.start)} --> {format_srt_time(seg.end)}")
                        srt_lines.append(seg.text.strip())
                        srt_lines.append("")
                        
                        percent = min(seg.end / total_duration, 1.0)
                        progress_bar_srt.progress(percent)
                        status_text.text(
                            f"Đang nhận diện: {seg.end:.1f}s / {total_duration:.1f}s ({percent*100:.0f}%) — "
                            f"\"{seg.text.strip()[:40]}...\""
                        )
                    
                    srt_content = "\n".join(srt_lines)
                    progress_bar_srt.empty()
                    status_text.empty()
                    
                    if not srt_content.strip():
                        st.warning("Không nhận diện được giọng nói nào trong file. Thử lại với model lớn hơn hoặc kiểm tra file âm thanh.")
                    else:
                        st.success(f"✅ Đã tạo SRT thành công! (Ngôn ngữ nhận diện: {info.language})")
                        st.text_area("Xem trước nội dung SRT:", srt_content[:2000], height=250)
                        st.download_button(
                            "💾 Tải File .SRT",
                            data=srt_content,
                            file_name=f"{os.path.splitext(media_file.name)[0]}.srt",
                            mime="text/plain"
                        )
                except Exception as e:
                    st.error(f"Lỗi khi nhận diện giọng nói: {e}")
                finally:
                    if os.path.exists(temp_media_path):
                        os.remove(temp_media_path)
    
    # ---------- CHẾ ĐỘ 2: TỰ NHẬP VĂN BẢN ----------
    else:
        st.caption("Dán văn bản, mỗi dòng = 1 câu phụ đề. Hệ thống tự chia thời gian đều theo tổng thời lượng bạn nhập.")
        
        text_input_srt = st.text_area(
            "Dán văn bản (mỗi dòng 1 câu phụ đề):",
            height=200,
            placeholder="Xin chào các bạn\nHôm nay chúng ta sẽ học...\nBài học đầu tiên là..."
        )
        
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            timing_mode = st.radio("Cách chia thời gian:", ["Theo tổng thời lượng video", "Số giây cố định mỗi dòng"])
        with col_m2:
            if timing_mode == "Theo tổng thời lượng video":
                total_duration = st.number_input("Tổng thời lượng (giây):", min_value=1.0, value=60.0, step=1.0)
            else:
                seconds_per_line = st.number_input("Số giây mỗi dòng:", min_value=0.5, value=3.0, step=0.5)
        
        if st.button("🚀 Tạo File SRT", key="btn_generate_srt_manual"):
            lines = [l.strip() for l in text_input_srt.split("\n") if l.strip()]
            if not lines:
                st.warning("Vui lòng nhập ít nhất 1 dòng văn bản!")
            else:
                srt_lines = []
                current_time = 0.0
                
                if timing_mode == "Theo tổng thời lượng video":
                    # Chia đều theo độ dài ký tự của mỗi dòng để câu dài có nhiều thời gian hơn
                    total_chars = sum(len(l) for l in lines) or 1
                    for idx, line in enumerate(lines, start=1):
                        duration = max(1.0, (len(line) / total_chars) * total_duration)
                        start_t = current_time
                        end_t = current_time + duration
                        srt_lines.append(str(idx))
                        srt_lines.append(f"{format_srt_time(start_t)} --> {format_srt_time(end_t)}")
                        srt_lines.append(line)
                        srt_lines.append("")
                        current_time = end_t
                else:
                    for idx, line in enumerate(lines, start=1):
                        start_t = current_time
                        end_t = current_time + seconds_per_line
                        srt_lines.append(str(idx))
                        srt_lines.append(f"{format_srt_time(start_t)} --> {format_srt_time(end_t)}")
                        srt_lines.append(line)
                        srt_lines.append("")
                        current_time = end_t
                
                srt_content = "\n".join(srt_lines)
                st.success(f"✅ Đã tạo SRT thành công! ({len(lines)} câu, tổng thời lượng ~{current_time:.1f} giây)")
                st.text_area("Xem trước nội dung SRT:", srt_content[:2000], height=250)
                st.download_button(
                    "💾 Tải File .SRT",
                    data=srt_content,
                    file_name=f"Sub_Tao_Thu_Cong_{int(time.time())}.srt",
                    mime="text/plain"
                )

if selected == "Nhân Bản Giọng":
    st.subheader("🧬 Nhân Bản Giọng Nói (Voice Cloning)")
    st.caption("Tải lên 1 mẫu giọng nói (6-30 giây, càng rõ càng tốt) + file .SRT, AI sẽ đọc bằng giọng đó.")
    st.info("⚠️ Chỉ dùng giọng của bạn hoặc người đã đồng ý. Model XTTS-v2 chỉ miễn phí cho mục đích cá nhân, phi thương mại.")
    
    col_vc1, col_vc2 = st.columns(2)
    with col_vc1:
        voice_sample = st.file_uploader("Mẫu giọng nói mẫu (.wav, .mp3):", type=["wav", "mp3"], key="voice_sample_uploader")
    with col_vc2:
        srt_clone_file = st.file_uploader("File .SRT cần đọc:", type=["srt"], key="srt_clone_uploader")
    
    st.caption("XTTS-v2 gốc chưa hỗ trợ clone tiếng Việt. Voice TTS vẫn hỗ trợ giọng tiếng Việt.")
    clone_lang = st.selectbox(
        "Ngôn ngữ văn bản trong SRT:",
        ["en", "zh-cn", "ja", "ko", "fr", "de", "es"],
        format_func=lambda x: {"vi": "Tiếng Việt", "en": "Tiếng Anh", "zh-cn": "Tiếng Trung",
                                "ja": "Tiếng Nhật", "ko": "Tiếng Hàn", "fr": "Tiếng Pháp",
                                "de": "Tiếng Đức", "es": "Tiếng Tây Ban Nha"}.get(x, x)
    )
    
    if st.button("🚀 Bắt Đầu Nhân Bản Giọng", key="btn_voice_clone"):
        if not voice_sample or not srt_clone_file:
            st.warning("Vui lòng tải lên đủ cả mẫu giọng nói và file SRT!")
        else:
            sample_path = f"temp_audio/voice_sample_{int(time.time())}{Path(voice_sample.name).suffix.lower()}"
            with open(sample_path, "wb") as f:
                f.write(voice_sample.read())

            temp_srt_clone = f"outputs/temp_clone_{int(time.time())}.srt"
            with open(temp_srt_clone, "wb") as f:
                f.write(srt_clone_file.read())

            output_clone_path = f"outputs/Voice_Clone_{int(time.time())}.wav"
            worker_python = sys.executable
            worker_script = str(APP_DIR / "voice_clone_worker.py")

            progress_bar_vc = st.progress(0)
            status_text_vc = st.empty()

            try:
                worker_env = os.environ.copy()
                worker_env["COQUI_TOS_AGREED"] = "1"  # tự động đồng ý điều khoản license, tránh treo chờ input

                process = subprocess.Popen(
                    [worker_python, worker_script,
                     "--sample", sample_path,
                     "--srt", temp_srt_clone,
                     "--lang", clone_lang,
                     "--output", output_clone_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=worker_env,
                    cwd=str(SESSION_DIR),
                    encoding="utf-8",
                    errors="replace"
                )

                total_lines_est = 1
                all_output_lines = []
                for line in process.stdout:
                    line = line.strip()
                    all_output_lines.append(line)
                    if line == "LOADING_MODEL":
                        status_text_vc.text("Đang tải model AI (lần đầu ~2GB, hơi lâu)...")
                    elif line.startswith("PROGRESS"):
                        try:
                            info = line.replace("PROGRESS ", "")
                            frac_str, preview = info.split(":", 1)
                            cur, total = frac_str.split("/")
                            cur, total = int(cur), int(total)
                            total_lines_est = total
                            progress_bar_vc.progress(min(cur / total, 1.0))
                            status_text_vc.text(f"Đang nhân bản giọng câu {cur}/{total}: {preview.strip()}...")
                        except Exception:
                            pass
                    elif line.startswith("WARNING"):
                        st.warning(f"⚠️ {line.replace('WARNING ', '')}")
                    elif line == "DONE":
                        status_text_vc.text("Hoàn tất, đang xuất file...")

                process.wait()
                progress_bar_vc.empty()
                status_text_vc.empty()

                if process.returncode == 0 and os.path.exists(output_clone_path):
                    st.success("🎉 Đã nhân bản giọng nói thành công!")
                    st.audio(output_clone_path, format="audio/wav")
                    with open(output_clone_path, "rb") as f_out:
                        st.download_button("💾 Tải File Audio", data=f_out, file_name=os.path.basename(output_clone_path), mime="audio/wav")
                else:
                    st.error(f"Lỗi khi nhân bản giọng nói (mã lỗi: {process.returncode}).")
                    with st.expander("📋 Xem log chi tiết"):
                        st.code("\n".join(all_output_lines) if all_output_lines else "(Không có log nào được ghi lại)")
            finally:
                if os.path.exists(sample_path):
                    os.remove(sample_path)
                if os.path.exists(temp_srt_clone):
                    os.remove(temp_srt_clone)

if selected == "Văn Bản Cảm Xúc":
    st.subheader("🎭 Đọc Văn Bản Có Cảm Xúc (Tag Giả Lập)")
    st.caption(
        "Gõ văn bản kèm tag trong ngoặc vuông để tự động chỉnh tốc độ/cao độ giọng đọc theo cảm xúc. "
        "Tag chỉ ảnh hưởng đến đoạn văn bản đứng SAU nó."
    )

    with st.expander("📋 Danh sách tag được hỗ trợ"):
        st.write(", ".join(f"`[{t}]`" for t in TAG_PRESETS.keys()))
        st.caption("Tag không có trong danh sách vẫn được loại bỏ khỏi lời đọc, nhưng không thay đổi giọng.")

    emotion_text = st.text_area(
        "Nhập văn bản (kèm tag):",
        height=200,
        placeholder="Xin chào các bạn. [laughing] Hôm nay tôi rất vui vì... [sighs] nhưng cũng hơi mệt."
    )

    col_e1, col_e2 = st.columns(2)
    with col_e1:
        emotion_voice_label = st.selectbox("Chọn Giọng Đọc:", list(VOICE_OPTIONS.keys()), key="emotion_voice_select")
        emotion_voice = VOICE_OPTIONS[emotion_voice_label]
    with col_e2:
        base_speed = st.slider("Tốc độ đọc gốc (%):", -50, 100, 0, 5, key="emotion_base_speed")
        base_pitch = st.slider("Cao độ gốc (%):", -50, 50, 0, 5, key="emotion_base_pitch")

    if st.button("🚀 Tạo Giọng Đọc Cảm Xúc", key="btn_emotion_tts"):
        if not emotion_text.strip():
            st.warning("Vui lòng nhập văn bản!")
        else:
            segments, unknown_tags = parse_emotion_text(emotion_text)

            if not segments:
                st.warning("Không có đoạn văn bản nào để đọc (có thể toàn bộ chỉ là tag).")
            else:
                if unknown_tags:
                    st.info(f"ℹ️ Các tag sau không nằm trong danh sách hỗ trợ, sẽ bị bỏ qua (không đổi giọng): {', '.join(unknown_tags)}")

                progress_bar_em = st.progress(0)
                status_text_em = st.empty()
                final_audio = AudioSegment.silent(duration=0, frame_rate=24000)
                total_segs = len(segments)

                for idx, (seg_text, rate_delta, pitch_delta) in enumerate(segments):
                    status_text_em.text(f"Đang tạo giọng đọc đoạn {idx+1}/{total_segs}: {seg_text[:30]}...")

                    final_rate = max(-50, min(150, base_speed + rate_delta))
                    final_pitch = max(-50, min(50, base_pitch + pitch_delta))
                    rate_str = f"{final_rate:+d}%"
                    pitch_str = f"{final_pitch:+d}Hz"

                    temp_seg_file = f"temp_audio/emotion_seg_{idx}.mp3"
                    seg_audio = None
                    # Ước lượng độ dài tối thiểu hợp lý (ms) dựa theo số ký tự, để phát hiện audio bị cắt đầu
                    min_expected_ms = max(400, len(seg_text) * 55)

                    for attempt in range(4):
                        try:
                            if os.path.exists(temp_seg_file):
                                os.remove(temp_seg_file)
                            generate_single_tts(seg_text, emotion_voice, rate_str, pitch_str, temp_seg_file)
                            if os.path.exists(temp_seg_file) and os.path.getsize(temp_seg_file) > 100:
                                candidate_audio = AudioSegment.from_file(temp_seg_file)
                                if len(candidate_audio) >= min_expected_ms:
                                    seg_audio = candidate_audio.set_frame_rate(24000).set_channels(1).set_sample_width(2)
                                    break
                                # Audio ngắn bất thường -> nghi bị cắt mất từ đầu, thử lại
                        except Exception:
                            seg_audio = None
                        time.sleep(0.8 * (attempt + 1))

                    time.sleep(0.15)

                    if seg_audio is None:
                        st.warning(f"⚠️ Bỏ qua đoạn {idx+1} (không tạo được giọng đọc)")
                    else:
                        # Cắt bớt khoảng lặng thừa ở đầu/cuối mỗi đoạn do chính edge-tts tự thêm vào
                        seg_audio = seg_audio.strip_silence(silence_thresh=-40, padding=50)
                        
                        if len(final_audio) == 0:
                            final_audio += seg_audio
                        else:
                            # Crossfade nhẹ để nối mượt giữa 2 đoạn, tránh nghe rời rạc
                            crossfade_ms = min(60, len(seg_audio) // 4, len(final_audio) // 4)
                            final_audio = final_audio.append(seg_audio, crossfade=crossfade_ms)

                    if os.path.exists(temp_seg_file):
                        os.remove(temp_seg_file)

                    progress_bar_em.progress((idx + 1) / total_segs)

                output_emotion_path = f"outputs/Emotion_Voice_{int(time.time())}.wav"
                final_audio.export(output_emotion_path, format="wav")

                progress_bar_em.empty()
                status_text_em.empty()
                st.success("✅ Đã tạo giọng đọc cảm xúc thành công!")
                st.audio(output_emotion_path, format="audio/wav")
                with open(output_emotion_path, "rb") as f_out:
                    st.download_button("💾 Tải File Audio", data=f_out, file_name=os.path.basename(output_emotion_path), mime="audio/wav")
