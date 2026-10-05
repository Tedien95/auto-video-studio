import os
import runpy
import shutil
import sys
import threading
import uuid
from pathlib import Path
import streamlit as st
from filelock import FileLock, Timeout

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
from cleanup import cleanup_sessions

root = Path(os.environ.get('DATA_ROOT', str(APP_DIR / 'data'))).resolve()
root.mkdir(parents=True, exist_ok=True)
os.environ['DATA_ROOT'] = str(root)

@st.cache_resource
def start_cleanup(data_root):
    def run():
        while True:
            try:
                cleanup_sessions(data_root, retention_hours=24)
            except OSError:
                pass
            threading.Event().wait(3600)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread

start_cleanup(str(root))
locks = root / 'locks'
locks.mkdir(parents=True, exist_ok=True)
if 'workspace_id' not in st.session_state:
    st.session_state.workspace_id = uuid.uuid4().hex
session = root / 'sessions' / st.session_state.workspace_id

try:
    with FileLock(str(locks / 'processing.lock'), timeout=0):
        stored = sum(p.stat().st_size for p in (root / 'sessions').rglob('*') if p.is_file())
        if stored > 900 * 1024 * 1024 or shutil.disk_usage(root).free < 500 * 1024 * 1024:
            st.error('Bộ nhớ lưu trữ tạm đang gần đầy. Hãy tải kết quả đã có và thử lại sau khi dữ liệu cũ được dọn.')
            st.stop()
        with FileLock(str(locks / (session.name + '.lock'))):
            session.mkdir(parents=True, exist_ok=True)
            (session / '.last_used').touch()
            try:
                runpy.run_path(str(APP_DIR / 'app.py'), run_name='__main__')
            finally:
                (session / '.last_used').touch()
except Timeout:
    st.info('Ứng dụng đang xử lý một tác vụ khác. Vui lòng đợi rồi tải lại trang.')
