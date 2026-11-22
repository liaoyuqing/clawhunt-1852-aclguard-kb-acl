import os
import zipfile

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPTS)
OUT = os.path.join(os.path.dirname(ROOT), "aclguard-1852.zip")
SKIP = {".venv", "__pycache__", ".pytest_cache"}

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
    count = 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP]
        for name in filenames:
            if name.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
            zf.write(full, "aclguard-1852/" + rel)
            count += 1
print("files", count)
print("size", os.path.getsize(OUT))