"""在线更新（v2.26）：从 GitHub 仓库下载新版本，用和「上传升级包」同一套流程升级（先备份程序，不碰数据）。

发版：开发者把代码推到 GitHub 的 main 分支（app.py 里的 VERSION 就是版本号）。
NAS：每 12 小时检查一次 main 分支的版本是不是比现在新（设置里可以关），有就在「系统检查与升级」页和顶部提示；
     老板点「立即更新」才会下载并升级、自动重启。

私有仓库要在设置里填 GitHub 只读令牌（只存在 NAS 上，不发回浏览器，也不写进日志）。

★ 对外：status()  check(force=False)  apply(tag=None, user="")  start_background()
"""
import json
import os
import re
import threading
import time

from .config import DATA_DIR, load_config

API = "https://api.github.com"
BRANCH = "main"
STATE_PATH = os.path.join(DATA_DIR, "update_state.json")
CHECK_EVERY = 12 * 3600
_lock = threading.Lock()
_busy = {"on": False, "step": ""}


def _state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(st):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_PATH + ".tmp", "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(STATE_PATH + ".tmp", STATE_PATH)


def _vt(v):
    from .sysadmin import _vtuple
    return _vtuple(str(v).lstrip("vV"))


def _repo(cfg):
    r = str(cfg.get("update_repo") or "").strip().strip("/")
    r = re.sub(r"^https?://github\.com/", "", r)
    r = re.sub(r"\.git$", "", r)
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", r):
        raise ValueError("设置里「GitHub 仓库」要写成 拥有者/仓库名，例如 smallyjh-boop/3d-ops")
    return r


def _headers(cfg, raw=False):
    h = {"Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "3d-ops-updater"}
    tok = str(cfg.get("update_token") or "").strip()
    if tok:
        h["Authorization"] = "Bearer " + tok
    return h


def _get(cfg, path, raw=False, timeout=30, stream=False):
    import requests
    try:
        r = requests.get(API + path, headers=_headers(cfg, raw), timeout=timeout, stream=stream)
    except requests.RequestException as e:
        raise RuntimeError(f"NAS 连不上 GitHub（{type(e).__name__}），检查网络后再试") from e
    if r.status_code == 401:
        raise RuntimeError("GitHub 令牌不对或已经过期：到 GitHub 重新生成一个，填到 设置 → 通用 → 在线更新")
    if r.status_code == 404:
        raise RuntimeError("找不到仓库：检查「GitHub 仓库」名字；私有仓库要填令牌，并且令牌要有这个仓库的读取权限")
    if r.status_code == 403:
        raise RuntimeError("GitHub 拒绝访问（令牌权限不够，或检查太频繁，过一小时再试）")
    if r.status_code != 200:
        raise RuntimeError(f"GitHub 返回 HTTP {r.status_code}")
    return r


def _notes(cfg, repo, tag, cur):
    """README.txt 里比现在新的版本说明（每个版本一段）。"""
    try:
        text = _get(cfg, f"/repos/{repo}/contents/README.txt?ref={tag}", raw=True).text
    except Exception:  # noqa: BLE001  拿不到说明不影响升级
        return []
    out = []
    for m in re.finditer(r"^ {2,4}v(\d+\.\d+\.\d+)：(.*)\n((?:(?! {2,4}v\d+\.\d+\.\d+：).*\n)*)", text, re.M):
        ver = m.group(1)
        if _vt(ver) <= _vt(cur):
            continue
        lines = [x.strip() for x in m.group(3).splitlines() if x.strip().startswith("·")]
        out.append({"version": ver, "title": m.group(2).strip(), "points": [x.lstrip("· ").strip() for x in lines][:12]})
    out.sort(key=lambda x: _vt(x["version"]), reverse=True)
    return out[:8]


def status():
    from .sysadmin import current_version
    cfg = load_config()
    st = _state()
    cur = current_version()
    latest = st.get("latest") or ""
    return {"current": cur, "latest": latest, "available": bool(latest) and _vt(latest) > _vt(cur),
            "notes": st.get("notes") or [], "checked_at": st.get("checked_at"), "error": st.get("error") or "",
            "repo": cfg.get("update_repo") or "", "token_set": bool(str(cfg.get("update_token") or "").strip()),
            "auto": bool(cfg.get("update_check")), "busy": dict(_busy)}


def _latest(cfg, repo):
    """最新版本：main 分支最新提交里 app.py 的 VERSION（不需要打标签）。返回 (版本, 提交号)。"""
    c = _get(cfg, f"/repos/{repo}/commits/{BRANCH}").json()
    sha = str(c.get("sha") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("仓库里还没有程序（main 分支是空的）")
    from .sysadmin import _version_of
    ver = _version_of(_get(cfg, f"/repos/{repo}/contents/app.py?ref={sha}", raw=True).text)
    if not ver:
        raise RuntimeError("仓库里的 app.py 认不出版本号")
    return ver, sha


def check(force=True):
    """问 GitHub 最新的版本。force=False 时距离上次检查不到 12 小时就不问。"""
    from .sysadmin import current_version
    st = _state()
    if not force and time.time() - (st.get("checked_at") or 0) < CHECK_EVERY:
        return status()
    cfg = load_config()
    try:
        repo = _repo(cfg)
        latest, sha = _latest(cfg, repo)
        cur = current_version()
        st = {"checked_at": time.time(), "latest": latest, "tag": sha, "error": "",
              "notes": _notes(cfg, repo, sha, cur) if _vt(latest) > _vt(cur) else []}
    except (RuntimeError, ValueError) as e:
        st.update(checked_at=time.time(), error=str(e))
    _save(st)
    return status()


def apply(tag=None, user=""):
    """下载这个版本（默认最新）并升级。返回 sysadmin.upgrade 的结果；调用方负责重启。"""
    from . import sysadmin
    with _lock:
        if _busy["on"]:
            raise RuntimeError("正在更新中")
        _busy.update(on=True, step="检查版本")
    path = os.path.join(DATA_DIR, "tmp", "github_update.zip")
    try:
        cfg = load_config()
        repo = _repo(cfg)
        if not tag:
            st = check(force=True)
            if st["error"]:
                raise RuntimeError(st["error"])
            if not st["available"]:
                raise RuntimeError(f"已经是最新版本 v{st['current']}")
            tag = _state().get("tag")
        if not re.fullmatch(r"v?\d+\.\d+\.\d+|[0-9a-f]{40}", str(tag)):
            raise ValueError("版本号不对")
        _busy["step"] = "下载新版本"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        r = _get(cfg, f"/repos/{repo}/zipball/{tag}", timeout=300, stream=True)
        size = 0
        with open(path + ".part", "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
                size += len(chunk)
                if size > 300 * 1024 * 1024:
                    raise RuntimeError("下载的文件太大，停止了")
        os.replace(path + ".part", path)
        _busy["step"] = "安装新版本"
        res = sysadmin.upgrade(path, user=user)
        res["source"] = f"GitHub {repo} {str(tag)[:7]}"
        return res
    finally:
        _busy.update(on=False, step="")
        for p in (path, path + ".part"):
            try:
                os.remove(p)
            except OSError:
                pass


def start_background():
    """开机后每 12 小时检查一次（只检查，不升级）。"""
    if os.environ.get("LH_NO_UPDATE_CHECK"):
        return

    def loop():
        time.sleep(60)
        while True:
            try:
                if load_config().get("update_check"):
                    check(force=False)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(3600)
    threading.Thread(target=loop, daemon=True, name="update-check").start()
