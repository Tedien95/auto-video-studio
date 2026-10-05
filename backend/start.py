import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

os.chdir(Path(__file__).resolve().parent)
command = [sys.executable, '-m', 'streamlit', 'run', 'app.py',
           '--server.port=' + os.environ.get('PORT', '8501')]
backend_url = os.environ.get('BACKEND_PUBLIC_URL', '').strip()
if backend_url:
    parsed = urlparse(backend_url)
    if parsed.scheme != 'https' or not parsed.hostname:
        raise SystemExit('BACKEND_PUBLIC_URL must be an HTTPS URL.')
    command += ['--browser.serverAddress=' + parsed.hostname, '--browser.serverPort=443']
raise SystemExit(subprocess.call(command))
