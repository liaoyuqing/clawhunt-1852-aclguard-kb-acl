"""打包交付物：输出到仓库目录之外，避免 zip 进入自身摘要。"""
import os
import zipfile

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPTS)
OUT = os.path.join(os.path.dirname(ROOT), "aclguard-1852.zip")
SKIP = {".venv", "__pycache__", ".pytest_cache", ".git"}


def main():
    tmp = OUT + ".tmp"
    count = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in SKIP]
            for name in filenames:
                if name.endswith(".pyc") or name == "aclguard-1852.zip":
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
                zf.write(full, "aclguard-1852/" + rel)
                count += 1
    os.replace(tmp, OUT)
    print("files", count)
    print("size", os.path.getsize(OUT))


if __name__ == "__main__":
    main()
