import json
import os
import subprocess
from pathlib import Path
import streamlit as st

MAX_FILE_BYTES = 50 * 1024 * 1024

def config_value(name, default=None):
    if name in os.environ:
        return os.environ[name]
    try:
        return st.secrets.get(name, default)
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return default

def check_media(path, max_seconds=180):
    path = Path(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('File vượt giới hạn 50 MB của bản miễn phí.')
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path)],
        capture_output=True, text=True, timeout=20,
    )
    if result.returncode:
        raise ValueError('Không đọc được file video/audio. Hãy kiểm tra định dạng file.')
    try:
        duration = float(json.loads(result.stdout)['format']['duration'])
    except (KeyError, ValueError, TypeError):
        raise ValueError('Không xác định được thời lượng file.')
    if not 0 < duration <= max_seconds:
        raise ValueError(f'Bản miễn phí hỗ trợ tối đa {max_seconds // 60} phút cho thao tác này.')
    return duration

def check_subtitles(subs):
    if not subs:
        raise ValueError('File SRT không có câu phụ đề hợp lệ.')
    if len(subs) > 120 or sum(len(sub.text) for sub in subs) > 10000:
        raise ValueError('Bản miễn phí hỗ trợ tối đa 120 câu và 10.000 ký tự mỗi file SRT.')
    if max(sub.end.ordinal for sub in subs) > 300000:
        raise ValueError('File SRT cần có thời lượng tối đa 5 phút.')

def download_limit(progress):
    duration = (progress.get('info_dict') or {}).get('duration')
    if duration is not None and duration > 300:
        raise ValueError('Bản miễn phí tải video/audio tối đa 5 phút.')
    if (progress.get('downloaded_bytes') or 0) > MAX_FILE_BYTES:
        raise ValueError('Tải xuống đã vượt giới hạn 50 MB.')

def render_command(video, audio, output):
    return [
        'ffmpeg', '-y', '-i', str(video), '-i', str(audio),
        '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '1',
        '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2',
        '-b:v', '1000k', '-maxrate', '1000k', '-bufsize', '2000k',
        '-map', '0:v:0', '-map', '1:a:0', '-c:a', 'aac', '-b:a', '128k',
        '-movflags', '+faststart', '-shortest', str(output),
    ]
