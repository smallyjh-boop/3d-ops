"""环境自检：打印 Python、依赖版本和网络连通情况。"""
import io
import importlib
from importlib import metadata
import platform
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

print(f"Python  {sys.version.split()[0]}  ({platform.system()} {platform.release()}, {platform.machine()})")
ok = True
for mod, name in [("flask", "Flask"), ("openpyxl", "openpyxl"), ("PIL", "Pillow"), ("requests", "requests")]:
    try:
        importlib.import_module(mod)
        print(f"  [OK] {name} {metadata.version(name)}")
    except Exception as e:
        ok = False
        print(f"  [缺少] {name}: {e}")
try:
    importlib.import_module("rembg")
    print("  [OK] rembg 去背景组件")
except Exception:
    print("  [--] rembg 去背景组件未安装（可选，运行 3_install_bg_removal.bat）")
try:
    importlib.import_module("pypdfium2")
    print("  [OK] pypdfium2 平台面单排版组件")
except Exception:
    print("  [--] pypdfium2 平台面单排版组件未安装（重新运行 1_setup.bat；不装也能原样打印平台面单）")
try:
    import requests
    for url in ("https://api.anthropic.com", "https://api.imgbb.com"):
        try:
            requests.get(url, timeout=8)
            print(f"  [OK] 可以连接 {url}")
        except Exception as e:
            print(f"  [注意] 连不上 {url}：{type(e).__name__}")
except Exception:
    pass
print("\n环境正常。" if ok else "\n有依赖缺失，请重新运行 1_setup.bat。")
