"""Delete only expired private session directories; never models or source."""
import os
import re
import shutil
import time
from pathlib import Path
from filelock import FileLock, Timeout

def cleanup_sessions(root, retention_hours=24, now=None):
    root = Path(root).resolve()
    sessions = root / "sessions"
    locks = root / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    removed = 0
    if not sessions.exists():
        return removed
    cutoff = (time.time() if now is None else now) - retention_hours * 3600
    for session in sessions.iterdir():
        if not re.fullmatch(r"[0-9a-f]{32}", session.name) or not session.is_dir() or session.is_symlink():
            continue
        target = session.resolve()
        if target.parent != sessions.resolve():
            continue
        try:
            with FileLock(str(locks / (session.name + ".lock")), timeout=0):
                marker = session / ".last_used"
                stamp = marker.stat().st_mtime if marker.exists() else session.stat().st_mtime
                if stamp < cutoff:
                    shutil.rmtree(target)
                    removed += 1
        except (Timeout, OSError):
            continue
    return removed

if __name__ == "__main__":
    retention = max(1, float(os.environ.get("RETENTION_HOURS", "24")))
    while True:
        removed = cleanup_sessions(os.environ["DATA_ROOT"], retention)
        if removed:
            print(f"Cleanup: removed {removed} expired sessions.", flush=True)
        time.sleep(3600)
