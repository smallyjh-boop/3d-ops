"""电脑加速程序（v2.20）：装在一直开着的电脑上，帮 NAS 做吃 CPU 的活（切片、读大模型、3D 预览、抠图、去水印）。

用法（一般双击 4_start_worker.bat 就行，第一次会问 NAS 地址和密钥）：
    python worker.py                         按 data/worker.json 里的设置运行
    python worker.py --setup                 重新填 NAS 地址和密钥
    python worker.py --server http://192.168.31.200:8790 --key lh_xxx [--name 办公室电脑] [--slots 2]

· 密钥在 NAS 网页：系统 → 电脑加速 →「生成密钥」（只能领活，不能看订单、改产品）。
· 和 NAS 的版本不一样时自动下载 NAS 上的程序更新自己，然后重启（4_start_worker.bat 会自动重新打开）。
· 关掉窗口就停；NAS 发现电脑不在线会自己做（只是慢一些）。
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
CONF = os.path.join(HERE, "data", "worker.json")
EXIT_UPDATED = 3
LOG = []


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    LOG.append(line)
    del LOG[:-200]


def my_version():
    try:
        with open(os.path.join(HERE, "app.py"), encoding="utf-8") as f:
            m = re.search(r'^VERSION\s*=\s*"([^"]+)"', f.read(), re.M)
        return m.group(1) if m else "0"
    except OSError:
        return "0"


def gpu_name():
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True, timeout=5,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout.strip().splitlines()[0] if r.returncode == 0 and r.stdout.strip() else ""
    except Exception:  # noqa: BLE001
        return ""


def load_conf():
    try:
        with open(CONF, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_conf(c):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    with open(CONF, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)


def setup(c):
    print("\n===== 电脑加速 设置 =====")
    s = input(f"NAS 上 3D 运营管理系统的地址（例 http://192.168.31.200:8790）[{c.get('server', '')}]：").strip() or c.get("server", "")
    if s and not s.startswith("http"):
        s = "http://" + s
    k = input("电脑加速密钥（NAS 网页：系统 → 电脑加速 → 生成密钥，lh_ 开头）：").strip() or c.get("key", "")
    n = input(f"这台电脑的名字 [{c.get('name') or platform.node()}]：").strip() or c.get("name") or platform.node()
    c.update(server=s.rstrip("/"), key=k, name=n[:40])
    save_conf(c)
    print("已保存到 data/worker.json\n")
    return c


class Worker:
    def __init__(self, server, key, name, slots=1):
        import requests
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {key}"
        self.server = server.rstrip("/")
        self.name = name
        self.slots = max(1, int(slots))
        self.free = threading.Semaphore(self.slots)
        self.stop = threading.Event()
        self.caps, self.info = [], {}
        self.version = my_version()
        self.server_version = ""
        self.done = self.failed = 0
        self.no_install = False
        self.paused = False          # v2.28 桌面端：暂停加速
        self.share = False           # v2.28 桌面端：也帮别人加速（默认只做自己的活）
        self.desktop = False
        self.auto_update = True
        self.current = ""            # 正在做什么（桌面端托盘显示）

    # ---- 报到 ----
    def detect(self):
        from core import accel, kernels
        self.caps, self.info = kernels.capabilities()
        log(f"这台电脑可以做：{'、'.join(accel.KINDS.get(c, c) for c in self.caps)}" +
            (f"；OrcaSlicer：{self.info.get('orca')}" if self.info.get("orca") else ""))
        for k, why in (self.info.get("missing") or {}).items():
            log(f"  {accel.KINDS.get(k, k)}做不了：{why}")

    # ---- 缺的组件自动装（抠图 rembg、去水印 LaMa 模型），装好后马上开始帮忙 ----
    installing = ""

    def auto_install(self):
        import importlib.util
        if self.no_install:
            return
        if importlib.util.find_spec("rembg") is None:
            self.installing = "正在安装抠图组件（约 200 MB）"
            log(self.installing + "…第一次要几分钟，装好前抠图还是 NAS 做")
            try:
                r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "rembg[cpu]"], capture_output=True, text=True,
                                   timeout=3600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                log("抠图组件装好了" if r.returncode == 0 else "抠图组件安装失败：" + (r.stderr or r.stdout)[-300:])
            except Exception as e:  # noqa: BLE001
                log(f"抠图组件安装失败：{e}")
            self.installing = ""
            self.detect()
            try:
                self.hello()
            except Exception:  # noqa: BLE001
                pass
        try:
            from core import imgtools
            if not imgtools.status().get("lama") and importlib.util.find_spec("onnxruntime"):
                self.installing = "正在下载去水印模型 LaMa（约 200 MB）"
                log(self.installing + "…")
                imgtools.install_lama()
                for _ in range(1800):
                    time.sleep(2)
                    if not imgtools.LAMA_JOB.get("running"):
                        break
                self.installing = ""
                log("去水印模型：" + ("好了" if imgtools.status().get("lama") else str(imgtools.LAMA_JOB.get("error") or "没装上")))
                self.detect()
        except Exception as e:  # noqa: BLE001
            self.installing = ""
            log(f"去水印模型下载失败：{e}")

    def hello(self):
        from core import accel
        body = {"name": self.name, "caps": self.caps, "cpu": os.cpu_count(), "gpu": self.gpu, "version": self.version,
                "proto": accel.PROTO, "slots": self.slots, "inpaint": self.info.get("inpaint", ""), "orca": self.info.get("orca", ""),
                "os": f"{platform.system()} {platform.release()}", "missing": self.info.get("missing") or {},
                "installing": self.installing, "paused": self.paused, "share": self.share, "desktop": self.desktop}
        r = self.s.post(self.server + "/api/v1/accel/hello", json=body, timeout=15)
        if r.status_code in (401, 403):
            raise PermissionError(r.json().get("error") or "密钥不对")
        r.raise_for_status()
        d = r.json()
        self.server_version = d.get("server_version") or ""
        return d

    def heartbeat(self):
        while not self.stop.wait(15):
            try:
                self.hello()
                if self.server_version and self.server_version != self.version and self.auto_update:
                    self.update()
            except PermissionError as e:
                log(f"NAS 拒绝：{e}")
            except Exception as e:  # noqa: BLE001
                log(f"连不上 NAS：{str(e)[:120]}（会一直重试）")

    # ---- 自动更新 ----
    def update(self):
        log(f"NAS 是 v{self.server_version}，这里是 v{self.version}：下载更新…")
        r = self.s.get(self.server + "/api/v1/accel/package", timeout=120)
        r.raise_for_status()
        tmp = tempfile.mkdtemp(prefix="upd_")
        try:
            zp = os.path.join(tmp, "pkg.zip")
            with open(zp, "wb") as f:
                f.write(r.content)
            with zipfile.ZipFile(zp) as z:
                for n in z.namelist():
                    if n.endswith("/") or n.startswith(("/", "..")) or ".." in n.split("/") or n.lower().endswith(".bat"):
                        continue
                    dest = os.path.join(HERE, n)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "wb") as f:
                        f.write(z.read(n))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        log("更新好了，重新启动…")
        self.stop.set()
        os._exit(EXIT_UPDATED)

    # ---- 干活 ----
    def loop(self):
        self.gpu = gpu_name()
        self.detect()
        while True:
            try:
                d = self.hello()
                break
            except PermissionError as e:
                log(f"NAS 拒绝：{e}。请检查密钥（python worker.py --setup 重新填）")
                time.sleep(30)
            except Exception as e:  # noqa: BLE001
                log(f"连不上 NAS {self.server}：{str(e)[:120]}，30 秒后重试")
                time.sleep(30)
        log(f"已连上 NAS（v{self.server_version}），名字「{self.name}」，同时做 {self.slots} 件。开着这个窗口就行。")
        if not d.get("enabled", True):
            log("提示：NAS 的设置里「电脑加速」是关着的，开了以后才会派活过来")
        if self.server_version and self.server_version != self.version and self.auto_update:
            self.update()
        threading.Thread(target=self.heartbeat, daemon=True).start()
        threading.Thread(target=self.auto_install, daemon=True).start()
        while not self.stop.is_set():
            if self.paused:
                time.sleep(2)
                continue
            self.free.acquire()
            try:
                r = self.s.get(self.server + "/api/v1/accel/next", params={"name": self.name, "caps": ",".join(self.caps), "wait": 25},
                               timeout=40)
            except Exception as e:  # noqa: BLE001
                self.free.release()
                log(f"领活失败：{str(e)[:120]}")
                time.sleep(5)
                continue
            if r.status_code == 204:
                self.free.release()
                continue
            if r.status_code != 200:
                self.free.release()
                log(f"领活失败：HTTP {r.status_code} {r.text[:120]}")
                time.sleep(10)
                continue
            threading.Thread(target=self.do, args=(r.json(),), daemon=True).start()

    def do(self, t):
        from core import accel, kernels
        tid, kind = t["id"], t["kind"]
        label = accel.KINDS.get(kind, kind)
        t0 = time.time()
        d = tempfile.mkdtemp(prefix="w_")
        try:
            files = {}
            for n in t.get("files") or []:
                r = self.s.get(f"{self.server}/api/v1/accel/task/{tid}/file/{n}", timeout=600)
                r.raise_for_status()
                ext = "".join(ch for ch in ((t.get("ext") or {}).get(n) or "") if ch.isalnum() or ch == ".")[:8]
                p = os.path.join(d, "in_" + n + ext)      # 保留扩展名（.3mf / .obj / .stl 按扩展名读）
                with open(p, "wb") as f:
                    f.write(r.content)
                files[n] = p
            mb = sum(os.path.getsize(p) for p in files.values()) / 1048576
            log(f"开始 {label}（{mb:.1f} MB）")
            self.current = label
            out_dir = os.path.join(d, "out")
            os.makedirs(out_dir, exist_ok=True)
            res, outs = kernels.execute(kind, t.get("params") or {}, files, out_dir)
            fh = {k: open(p, "rb") for k, p in outs.items()}
            try:
                r = self.s.post(f"{self.server}/api/v1/accel/task/{tid}/done", data={"result": json.dumps(res, ensure_ascii=False)},
                                files=fh, timeout=600)
            finally:
                for f in fh.values():
                    f.close()
            if r.status_code == 410:
                log(f"{label} 做完了，但 NAS 已经等不及自己做了（{time.time() - t0:.0f} 秒）")
            else:
                r.raise_for_status()
                self.done += 1
                log(f"完成 {label}，用时 {time.time() - t0:.1f} 秒")
        except Exception as e:  # noqa: BLE001
            final = isinstance(e, ValueError)
            self.failed += 1
            log(f"{label} 失败：{str(e)[:200]}" + ("" if final else "（交回 NAS 自己做）"))
            if not final:
                log(traceback.format_exc()[-800:])
            try:
                self.s.post(f"{self.server}/api/v1/accel/task/{tid}/fail", json={"error": str(e)[:2000], "final": final}, timeout=30)
            except Exception:  # noqa: BLE001
                pass
        finally:
            self.current = ""
            shutil.rmtree(d, ignore_errors=True)
            self.free.release()


def main():
    ap = argparse.ArgumentParser(description="3D 运营管理系统 · 电脑加速")
    ap.add_argument("--server")
    ap.add_argument("--key")
    ap.add_argument("--name")
    ap.add_argument("--slots", type=int)
    ap.add_argument("--setup", action="store_true")
    ap.add_argument("--no-update", action="store_true")
    a = ap.parse_args()
    c = load_conf()
    for k in ("server", "key", "name", "slots"):
        if getattr(a, k):
            c[k] = getattr(a, k)
    if a.setup or not c.get("server") or not c.get("key"):
        if not sys.stdin or not sys.stdin.isatty():
            print("还没设置 NAS 地址和密钥：python worker.py --server http://NAS:8790 --key lh_xxx")
            sys.exit(2)
        c = setup(c)
    elif a.server or a.key:
        save_conf(c)
    print(f"\n  3D 运营管理系统 · 电脑加速 v{my_version()}  →  {c['server']}\n  关掉这个窗口就停止（NAS 会自己做，只是慢一些）。\n")
    name = c.get("name") or ((c["name_prefix"] + "@" + platform.node())[:40] if c.get("name_prefix") else platform.node())
    w = Worker(c["server"], c["key"], name, c.get("slots") or max(1, min(2, (os.cpu_count() or 2) // 4)))
    w.auto_update = not a.no_update and not c.get("no_update")
    w.no_install = bool(c.get("no_install"))
    if c.get("orca_path"):
        from core import kernels
        kernels.ORCA_PATH = c["orca_path"]
    try:
        w.loop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
