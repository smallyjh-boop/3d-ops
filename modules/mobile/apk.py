"""安卓 App 安装包：GitHub 上自动编译好的（发布名 android-v<版本>，见 .github/workflows/android.yml），
NAS 取一份存在 data/android/，手机在局域网里直接从 NAS 下载（http://NAS:8790/apk），不用连 GitHub、不用登录。
GitHub 仓库和只读令牌用「在线更新」的设置（设置 → 通用 → 在线更新）。连不上 GitHub 时老板也可以手动上传 APK。

对外：status()  fetch_latest(user)  upload(file, version, user)  local_file()
"""
import json
import os
import re
import threading
import time

from core.config import DATA_DIR, load_config

DIR = os.path.join(DATA_DIR, "android")
STATE = os.path.join(DIR, "state.json")
TAG_RE = re.compile(r"^android-v(\d+(?:\.\d+){0,3})$")
MAX_APK = 200 * 1024 * 1024
_lock = threading.Lock()


def _state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(st):
    os.makedirs(DIR, exist_ok=True)
    with open(STATE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(STATE + ".tmp", STATE)


def local_file():
    """NAS 上现在的安装包 (路径, 版本)；没有返回 (None, None)。"""
    st = _state()
    p = os.path.join(DIR, st.get("file") or "")
    if st.get("file") and os.path.isfile(p):
        return p, st.get("version") or ""
    return None, None


def status():
    st = _state()
    p, ver = local_file()
    cfg = load_config()
    return {"have": bool(p), "version": ver or "", "source": st.get("source") or "", "at": st.get("at"), "by": st.get("by") or "",
            "size": os.path.getsize(p) if p else 0, "repo": str(cfg.get("update_repo") or ""), "latest": st.get("latest") or None,
            "checked_at": st.get("checked_at"), "error": st.get("error") or ""}


def _pick(releases):
    """最新的 android-v… 发布里的 APK（优先 release 版，没有就 debug 版）。"""
    best = None
    for r in releases or []:
        m = TAG_RE.match(str(r.get("tag_name") or ""))
        if not m or r.get("draft"):
            continue
        apks = [a for a in r.get("assets") or [] if str(a.get("name") or "").lower().endswith(".apk")]
        if not apks:
            continue
        apks.sort(key=lambda a: (0 if "release" in a["name"].lower() else 1, a["name"]))
        ver = tuple(int(x) for x in m.group(1).split("."))
        if best is None or ver > best[0]:
            best = (ver, r, apks[0])
    if not best:
        return None
    _v, r, a = best
    return {"tag": r["tag_name"], "version": TAG_RE.match(r["tag_name"]).group(1), "asset_id": a["id"], "name": a["name"],
            "size": a.get("size") or 0, "published_at": r.get("published_at") or "", "url": r.get("html_url") or ""}


def check_latest():
    """问 GitHub 最新的安卓版本（不下载）。"""
    from core import updater
    cfg = load_config()
    repo = updater._repo(cfg)
    r = updater._get(cfg, f"/repos/{repo}/releases?per_page=30")
    latest = _pick(r.json())
    st = _state()
    st.update(latest=latest, checked_at=time.time(), error="" if latest else "GitHub 上还没有安卓 App 的发布（android-v…）")
    _save(st)
    return latest


def fetch_latest(user=""):
    """从 GitHub 下载最新的安卓 App 到 NAS。返回 status()。"""
    from core import updater
    import requests
    with _lock:
        try:
            latest = check_latest()
        except (RuntimeError, ValueError) as e:
            st = _state(); st.update(error=str(e), checked_at=time.time()); _save(st)
            raise ValueError(str(e)) from e
        if not latest:
            raise ValueError("GitHub 上还没有安卓 App 的发布（android-v…），等编译好再试")
        p, ver = local_file()
        if p and ver == latest["version"] and _state().get("source") == "github":
            return status()
        cfg = load_config()
        repo = updater._repo(cfg)
        h = updater._headers(cfg)
        h["Accept"] = "application/octet-stream"
        try:
            r = requests.get(f"{updater.API}/repos/{repo}/releases/assets/{latest['asset_id']}", headers=h, timeout=60, stream=True)
        except requests.RequestException as e:
            raise ValueError(f"NAS 连不上 GitHub（{type(e).__name__}）") from e
        if r.status_code != 200:
            raise ValueError(f"下载安装包失败：GitHub 返回 HTTP {r.status_code}")
        os.makedirs(DIR, exist_ok=True)
        name = f"3dops-{latest['version']}.apk"
        tmp = os.path.join(DIR, name + ".part")
        n = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                n += len(chunk)
                if n > MAX_APK:
                    raise ValueError("安装包太大了，不对劲")
                f.write(chunk)
        _check_apk(tmp)
        os.replace(tmp, os.path.join(DIR, name))
        _cleanup(keep=name)
        st = _state()
        st.update(file=name, version=latest["version"], source="github", at=time.time(), by=user, error="")
        _save(st)
    return status()


def _check_apk(path):
    """APK 就是 zip，里面要有 AndroidManifest.xml。"""
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            if "AndroidManifest.xml" not in z.namelist():
                raise ValueError("这不是安卓安装包（APK）")
    except zipfile.BadZipFile as e:
        raise ValueError("这不是安卓安装包（APK）") from e


def _cleanup(keep):
    for n in os.listdir(DIR):
        if n.endswith(".apk") and n != keep:
            try:
                os.remove(os.path.join(DIR, n))
            except OSError:
                pass


def upload(file, version="", user=""):
    """老板手动上传 APK（NAS 连不上 GitHub 时）。"""
    version = re.sub(r"[^0-9A-Za-z._-]", "", str(version or ""))[:20] or time.strftime("%Y%m%d")
    os.makedirs(DIR, exist_ok=True)
    name = f"3dops-{version}.apk"
    tmp = os.path.join(DIR, name + ".part")
    file.save(tmp)
    if os.path.getsize(tmp) > MAX_APK:
        os.remove(tmp)
        raise ValueError("安装包太大了")
    try:
        _check_apk(tmp)
    except ValueError:
        os.remove(tmp)
        raise
    with _lock:
        os.replace(tmp, os.path.join(DIR, name))
        _cleanup(keep=name)
        st = _state()
        st.update(file=name, version=version, source="upload", at=time.time(), by=user, error="")
        _save(st)
    return status()
