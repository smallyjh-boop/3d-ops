"""系统检查 + 在线升级（只有老板能用）。

check()      一次看清：版本、依赖、磁盘、数据库、OrcaSlicer 和每台打印机的配置、AI、备份、客服。
upgrade()    上传新版本 zip → 先备份当前程序 → 覆盖程序文件（不碰 data）→ 需要时装新依赖 → 重启。
"""
import importlib.util
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

from . import db
from .config import DATA_DIR, load_config

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN_DOCKER = os.environ.get("LH_DOCKER") == "1"

# requirements.txt 里的包名 → import 名
IMPORT_NAME = {"pillow": "PIL", "pypdf": "pypdf", "flask": "flask", "openpyxl": "openpyxl",
               "requests": "requests", "waitress": "waitress", "numpy": "numpy", "zxing-cpp": "zxingcpp"}


def _item(group, name, status, detail="", fix=""):
    return {"group": group, "name": name, "status": status, "detail": detail, "fix": fix}


def _version_of(app_py_text):
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', app_py_text, re.M)
    return m.group(1) if m else ""


def _vtuple(v):
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", v or "0"))


def current_version():
    try:
        with open(os.path.join(APP_DIR, "app.py"), encoding="utf-8") as f:
            return _version_of(f.read())
    except OSError:
        return ""


def _requirements(path=None):
    path = path or os.path.join(APP_DIR, "requirements.txt")
    out = []
    try:
        for line in open(path, encoding="utf-8"):
            line = line.split("#")[0].strip()
            if line:
                out.append(re.split(r"[<>=!~\[ ]", line)[0].lower())
    except OSError:
        pass
    return out


def missing_packages():
    return [p for p in _requirements() if importlib.util.find_spec(IMPORT_NAME.get(p, p)) is None]


def _model_token(printer_name):
    """「Bambu Lab P1S」→ p1s；「Creality K1 Max」→ k1max（用来判断配置是不是这台打印机的）。"""
    n = re.sub(r"[^a-z0-9 ]", " ", (printer_name or "").lower())
    words = [w for w in n.split() if w not in ("bambu", "lab", "creality", "bbl", "printer", "3d")]
    return "".join(words)


def _profile_matches(printer_name, machine):
    tok = _model_token(printer_name)
    if not tok or not machine:
        return True
    m = re.sub(r"[^a-z0-9]", "", os.path.basename(machine).lower())
    return tok in m


# ---------------- 系统检查 ----------------
def check():
    items = []
    cfg = load_config()
    G = "程序"
    items.append(_item(G, "版本", "ok", f"v{current_version()} · Python {platform.python_version()} · "
                       + ("NAS / Docker" if IN_DOCKER else platform.system())))
    miss = missing_packages()
    items.append(_item(G, "依赖组件", "err" if miss else "ok",
                       ("缺少：" + ", ".join(miss)) if miss else f"{len(_requirements())} 个都已安装",
                       ("重启一次程序会自动安装（NAS：Container Station 里重启容器；Windows：重新运行 2_start.bat）" if miss else "")))
    importlib.invalidate_caches()
    if importlib.util.find_spec("rembg") is None:
        st = REMBG_JOB
        if st.get("running"):
            items.append(_item(G, "抠图组件（可选）", "warn", "正在安装…（大约 200MB，5–15 分钟，装好后点「重新检查」）"))
        else:
            it = _item(G, "抠图组件（可选）", "warn",
                       "没有安装，「一键去背景」不能用" + (f"。上次安装失败：{st['error']}" if st.get("error") else ""),
                       "点右边「安装」（需要联网，约 200MB）；不用抠图可以忽略")
            it["action"] = "install_rembg"
            items.append(it)
    else:
        items.append(_item(G, "抠图组件（可选）", "ok", "已安装，可以「一键去背景」（第一次使用会再下载约 170MB 模型）"))
    from . import imgtools
    ist = imgtools.status()
    if ist["lama"]:
        items.append(_item(G, "去水印增强模型 LaMa（可选）", "ok", "已安装：修图「去水印 / 去杂物」用 LaMa，效果最好"))
    else:
        lj = ist["lama_job"]
        if lj.get("running"):
            items.append(_item(G, "去水印增强模型 LaMa（可选）", "warn", f"正在下载… {lj.get('done_mb', 0)} / {lj.get('total_mb') or '约 208'} MB（装好后点「重新检查」）"))
        else:
            it = _item(G, "去水印增强模型 LaMa（可选）", "warn",
                       ("没有安装，去水印先用 OpenCV（小面积够用）" if ist["cv2"] else "没有安装，去水印只能处理很小的点")
                       + (f"。上次下载失败：{lj['error']}" if lj.get("error") else ""),
                       "点右边「安装」（需要联网，约 208MB，从 Hugging Face 下载）")
            it["action"] = "install_lama"
            items.append(it)

    G = "数据"
    try:
        du = shutil.disk_usage(DATA_DIR)
        free_gb = du.free / 1e9
        items.append(_item(G, "磁盘空间", "err" if free_gb < 1 else "warn" if free_gb < 5 else "ok",
                           f"剩余 {free_gb:.1f} GB", "清理旧文件或扩容" if free_gb < 5 else ""))
    except OSError as e:
        items.append(_item(G, "磁盘空间", "warn", str(e)))
    try:
        r = db.conn().execute("PRAGMA quick_check").fetchone()[0]
        size = os.path.getsize(db.DB_PATH) / 1e6 if os.path.exists(db.DB_PATH) else 0
        items.append(_item(G, "数据库", "ok" if r == "ok" else "err", f"{size:.1f} MB · 检查结果：{r}",
                           "" if r == "ok" else "用最近的备份恢复，并把这一行截图发给开发者"))
    except Exception as e:  # noqa: BLE001
        items.append(_item(G, "数据库", "err", str(e)))
    items += _check_backups()

    G = "切片 / 打印机"
    try:
        from . import slicer, orca_profiles as op
        exe = slicer.find_orca(cfg)
        if not exe:
            items.append(_item(G, "OrcaSlicer", "warn", "没有找到，自动切片不能用（可以上传电脑上切好的文件）",
                               "设置 → 生产「手动选择程序」；NAS 版第一次启动会自动安装"))
        else:
            idx = op.build_index(exe)
            sm = op.summary(idx)
            items.append(_item(G, "OrcaSlicer", "ok", f"{exe} · 打印机配置 {sm['machine']} 个"))
            from . import fleet
            for i, p in enumerate(cfg.get("printers") or slicer.DEFAULT_PRINTERS):
                name = f"{p.get('code') or ''} {p.get('name') or f'打印机 {i + 1}'}".strip()
                if fleet.tech_of(p) == "resin":
                    items.append(_item(G, name, "ok", "光固化：在电脑上切好后上传切片文件（不用 OrcaSlicer）"))
                    continue
                try:
                    _exe, _idx, machine, process, fil = slicer.resolve_profiles(cfg, i, "PLA")
                    raw = (p.get("orca_machine") or "").strip().strip('"')
                    note = ""
                    if raw and slicer._usable(idx, raw) != raw:
                        note = "（设置里存的配置在这台机器上找不到，已自动改用匹配的）"
                    if not _profile_matches(p.get("name"), machine):
                        items.append(_item(G, name, "warn", f"打印机配置是「{os.path.basename(machine)}」，看起来不是这台打印机的",
                                           "设置 → 生产 → 打印机：把这一行的打印机配置清空，再点「自动匹配配置」"))
                    else:
                        items.append(_item(G, name, "ok", f"打印机：{os.path.basename(machine)} · 工艺：{os.path.basename(process)}{note}"))
                except Exception as e:  # noqa: BLE001
                    items.append(_item(G, name, "err", str(e), "设置 → 生产 → 打印机：点「自动匹配配置」"))
    except Exception as e:  # noqa: BLE001
        items.append(_item(G, "OrcaSlicer", "warn", str(e)))

    from . import adimg
    if os.path.exists(adimg.FONT_CSS):
        items.append(_item("程序", "泰语字体（卖点图）", "ok", "Kanit / Prompt 已下载到本机"))
    else:
        items.append(_item("程序", "泰语字体（卖点图）", "warn", "还没下载：打开卖点图时会自动下载（要联网）；下载不了会用系统字体",
                           "保持联网，打开一次产品页后点「重新检查」"))
        adimg.thai_css()

    G = "AI 与客服"
    from . import ai as _ai
    _ok = _ai.ready(cfg, "copy")
    items.append(_item(G, "AI 接口密钥", "ok" if _ok else "err",
                       f"{cfg.get('ai_provider')} · {cfg.get('ai_model')}" if _ok else "没有填写：AI 文案和 AI 客服都不能用",
                       "" if _ok else "系统 → AI 接口"))
    try:
        c = db.conn()
        from . import modules as _mods
        _cs = _mods.public("cs")          # v2.30：客服是模块，关着就不检查客服的几项
        kb = c.execute("SELECT COUNT(*) FROM cs_kb WHERE active=1").fetchone()[0] if _cs else 0
        csd = _cs.data if _cs else None
        miss_p = csd.presets_missing() if csd else 0
        if csd:
            items.append(_item(G, "客服话术", "warn" if miss_p else "ok", f"常见问答 {kb} 条" + (f"，还有 {miss_p} 条新的标准话术没加" if miss_p else ""),
                           "客服 → 知识库与话术 →「＋ 补充标准话术」" if miss_p else ""))
        keys = c.execute("SELECT COUNT(*) FROM api_keys WHERE active=1").fetchone()[0] if _has_table(c, "api_keys") else 0
        items.append(_item(G, "扩展密钥", "ok" if keys else "warn", f"{keys} 个",
                           "" if keys else "设置 → 账号与权限「员工的扩展密钥」里给要用扩展的人新建密钥"))
        s = csd.settings() if csd else {}
        tg = bool(s.get("tg_token") and s.get("tg_chat"))
        if csd:
            items.append(_item(G, "未回复提醒（手机）", "ok" if tg else "warn", "已设置 Telegram" if tg else "没有设置，超时没回复只在系统里提醒",
                               "" if tg else "客服 → 知识库与话术 → 店铺政策下面「手机提醒」"))
    except Exception as e:  # noqa: BLE001
        items.append(_item(G, "客服", "warn", str(e)))

    n = {k: sum(1 for x in items if x["status"] == k) for k in ("ok", "warn", "err")}
    return {"items": items, "summary": n, "version": current_version(), "docker": IN_DOCKER, "time": time.time()}


REMBG_JOB = {}


def install_rembg():
    """在当前 Python 环境里后台安装抠图组件（Windows 和 NAS 都可以；NAS 装在 data 卷里，重建容器也不丢）。"""
    if REMBG_JOB.get("running"):
        return REMBG_JOB

    def run():
        REMBG_JOB.clear()
        REMBG_JOB.update(running=True, started=time.time())
        try:
            r = subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "-q", "rembg[cpu]", "opencv-python-headless"],
                               capture_output=True, text=True, timeout=3600)
            if r.returncode != 0:
                REMBG_JOB["error"] = (r.stderr or r.stdout or "")[-500:]
            else:
                importlib.invalidate_caches()
                REMBG_JOB["ok"] = True
        except Exception as e:  # noqa: BLE001
            REMBG_JOB["error"] = str(e)
        finally:
            REMBG_JOB["running"] = False
    threading.Thread(target=run, daemon=True, name="install-rembg").start()
    return {"running": True}


def _has_table(c, name):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def _check_backups():
    from . import extras
    G = "数据"
    bs = extras.backups()
    if not bs:
        return [_item(G, "备份", "warn", "还没有备份", "系统 → 数据备份 →「立即备份」")]
    last = bs[0]
    age_h = (time.time() - last["ts"]) / 3600
    out = [_item(G, "最近备份", "ok" if age_h < 48 else "warn",
                 f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(last['ts']))} · {last['size'] / 1e6:.1f} MB · 共 {len(bs)} 份",
                 "" if age_h < 48 else "超过 2 天没有备份：程序是不是一直没开？")]
    ok, msg = verify_backup(os.path.join(extras.BACKUP_DIR, last["name"]))
    out.append(_item(G, "备份能不能恢复", "ok" if ok else "err", msg,
                     "" if ok else "立即重新备份一次；还不行把这一行截图发给开发者"))
    copy_dir = (load_config().get("backup_copy_dir") or "").strip()
    if copy_dir:
        good = os.path.isdir(copy_dir)
        out.append(_item(G, "备份副本位置", "ok" if good else "err", copy_dir if good else f"找不到文件夹：{copy_dir}",
                         "" if good else "设置 → 通用「备份另存一份到」改成存在的文件夹（U 盘 / 网盘同步文件夹）"))
    else:
        out.append(_item(G, "备份副本位置", "warn", "备份只存在本机：硬盘坏了会一起丢",
                         ("NAS：用 HBS 3 把 Container/listing-helper/data/backups 每天同步到 U 盘或云盘" if IN_DOCKER
                          else "设置 → 通用「备份另存一份到」填一个 U 盘或网盘同步文件夹")))
    return out


def verify_backup(path):
    """打开备份 zip，把里面的数据库解出来做完整性检查（真正恢复前的演练）。"""
    try:
        with zipfile.ZipFile(path) as z:
            if "app.db" not in z.namelist():
                return False, "备份里没有数据库文件"
            n = len(z.namelist())
            d = tempfile.mkdtemp(prefix="bkcheck_")
            try:
                z.extract("app.db", d)
                c = sqlite3.connect(os.path.join(d, "app.db"))
                r = c.execute("PRAGMA quick_check").fetchone()[0]
                prods = c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
                c.close()
            finally:
                shutil.rmtree(d, ignore_errors=True)
        if r != "ok":
            return False, f"数据库检查不通过：{r}"
        return True, f"{os.path.basename(path)}：{n} 个文件，数据库正常（{prods} 张表）"
    except (zipfile.BadZipFile, OSError, sqlite3.Error) as e:
        return False, f"备份文件损坏：{e}"


# ---------------- 在线升级 ----------------
SKIP_TOP = {"data", ".venv", "__pycache__", ".git", ".github", "tests", "android"}   # tests：GitHub 下载的源码包里有测试，NAS 上用不到；android：安卓 App 的源码（GitHub 编译好发 APK）


def _members(z):
    """找出升级包里程序的根目录（有的包外面套了一层 3d-ops/）。返回 (前缀, 版本, requirements 内容)。"""
    names = z.namelist()
    cands = [n for n in names if n.endswith("app.py") and n.count("/") <= 1 and not n.startswith("__MACOSX")]
    for n in cands:
        prefix = n[:-len("app.py")]
        if any(x.startswith(prefix + "core/") for x in names) and any(x.startswith(prefix + "static/") for x in names):
            ver = _version_of(z.read(n).decode("utf-8", "replace"))
            req = z.read(prefix + "requirements.txt").decode("utf-8", "replace") if prefix + "requirements.txt" in names else ""
            return prefix, ver, req
    raise ValueError("这不是 3D 运营管理系统的升级包（里面要有 app.py、core、static）")


def backup_app():
    """升级前把当前程序文件打包存到 data/backups（升级出问题可以换回来）。"""
    from . import extras
    os.makedirs(extras.BACKUP_DIR, exist_ok=True)
    name = f"app_v{current_version()}_{time.strftime('%Y%m%d_%H%M%S')}.zip"
    path = os.path.join(extras.BACKUP_DIR, name)
    data_abs = os.path.abspath(DATA_DIR)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(APP_DIR):
            rel = os.path.relpath(root, APP_DIR)
            top = rel.split(os.sep)[0]
            if top in SKIP_TOP or os.path.abspath(root).startswith(data_abs):
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in SKIP_TOP]
            for f in files:
                if f.endswith(".pyc"):
                    continue
                z.write(os.path.join(root, f), os.path.normpath(os.path.join(rel, f)))
    # 程序备份只留最近 3 份
    olds = sorted(f for f in os.listdir(extras.BACKUP_DIR) if f.startswith("app_v") and f.endswith(".zip"))
    for o in olds[:-3]:
        try:
            os.remove(os.path.join(extras.BACKUP_DIR, o))
        except OSError:
            pass
    return name


def upgrade(zip_path, force=False, user=""):
    try:
        z = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise ValueError("文件不是 zip 压缩包")
    with z:
        prefix, new_ver, new_req = _members(z)
        cur = current_version()
        if not new_ver:
            raise ValueError("升级包里认不出版本号")
        if _vtuple(new_ver) < _vtuple(cur) and not force:
            raise ValueError(f"升级包是 v{new_ver}，比现在的 v{cur} 还旧。确定要换回旧版本，请勾选「允许降级」再上传")
        old_req = set(_requirements())
        saved = backup_app()
        written, skipped = 0, []
        root_abs = os.path.abspath(APP_DIR)
        for info in z.infolist():
            n = info.filename
            if not n.startswith(prefix) or n.endswith("/"):
                continue
            rel = n[len(prefix):]
            if not rel or rel.startswith("__MACOSX"):
                continue
            parts = rel.split("/")
            if parts[0] in SKIP_TOP or "__pycache__" in parts or rel.endswith(".pyc"):
                continue
            if rel.lower().endswith(".bat") and not IN_DOCKER:
                # Windows 正在运行的启动脚本不能边运行边改（会执行错乱），下次手动替换；NAS 上不运行 .bat，照常更新（v2.20.1）
                skipped.append(rel)
                continue
            dest = os.path.abspath(os.path.join(APP_DIR, rel))
            if not dest.startswith(root_abs + os.sep):
                continue   # 防止压缩包里有 ../ 路径
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tmp = dest + ".upg"
            with z.open(info) as src, open(tmp, "wb") as out:
                shutil.copyfileobj(src, out)
            os.replace(tmp, dest)
            written += 1
        removed = _remove_stale(z, prefix, root_abs)
    new_pkgs = sorted(set(_requirements()) - old_req)
    pip_msg = ""
    if not IN_DOCKER and (new_pkgs or missing_packages()):
        # Windows：在当前 Python 环境里装新依赖（NAS 重启时启动脚本会自动装）
        try:
            r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", os.path.join(APP_DIR, "requirements.txt")],
                               capture_output=True, text=True, timeout=900)
            pip_msg = "新依赖已安装" if r.returncode == 0 else ("安装依赖出错：" + (r.stderr or r.stdout)[-400:])
        except Exception as e:  # noqa: BLE001
            pip_msg = f"安装依赖出错：{e}"
    db.audit(user, "在线升级", f"v{cur}→v{new_ver}", f"{written} 个文件，删掉旧文件 {removed} 个，程序备份 {saved}")
    return {"from": cur, "to": new_ver, "files": written, "skipped": skipped, "app_backup": saved,
            "new_packages": new_pkgs, "pip": pip_msg, "restart": "auto" if IN_DOCKER else "manual"}


def _remove_stale(z, prefix, root_abs):
    """v2.30：功能搬进模块后，旧位置的文件（例如 core/cs/、web/fin.py）没用了。升级包里的 removed_files.txt 列出这些路径，
    升级时删掉（只删程序文件夹里的，不碰 data；升级前已经备份过程序）。"""
    try:
        text = z.read(prefix + "removed_files.txt").decode("utf-8")
    except KeyError:
        return 0
    n = 0
    for line in text.splitlines():
        rel = line.split("#")[0].strip().strip("/")
        if not rel or rel.split("/")[0] in SKIP_TOP or ".." in rel.split("/"):
            continue
        p = os.path.abspath(os.path.join(APP_DIR, rel))
        if not p.startswith(root_abs + os.sep):
            continue
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
                n += 1
            elif os.path.isfile(p):
                os.remove(p)
                n += 1
        except OSError:
            pass
    return n


def restart_later(delay=2.0):
    """NAS（Docker）：退出后容器会按「自动重启」策略重新启动，启动脚本顺便装好新依赖。"""
    def go():
        db.release()
        os._exit(3)
    threading.Timer(delay, go).start()


# ---------------- 外网访问（v2.26，Tailscale） ----------------
def tailscale_ips():
    """这台机器上的 Tailscale 地址（100.64.0.0/10）。Docker 容器不是主机网络时看不到，返回空。"""
    import ipaddress
    found = set()
    net = ipaddress.ip_network("100.64.0.0/10")
    try:
        with open("/proc/net/fib_trie", encoding="utf-8") as f:
            for m in re.finditer(r"(\d+\.\d+\.\d+\.\d+)\n\s+/32 host LOCAL", f.read()):
                if ipaddress.ip_address(m.group(1)) in net:
                    found.add(m.group(1))
    except (OSError, ValueError):
        pass
    if not found and shutil.which("tailscale"):
        try:
            r = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5)
            found.update(x.strip() for x in r.stdout.split() if x.strip())
        except Exception:  # noqa: BLE001
            pass
    return sorted(found)
