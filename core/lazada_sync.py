"""Lazada 全部类目的上架模板（v2.25）。

模板地址清单 core/data/lazada_templates.json 是在卖家中心（已登录的浏览器里）用
「เพิ่มสินค้าหลายรายการ → ดาวน์โหลดแม่แบบ」同一个接口批量生成的：每个文件 20 个类目，共 158 个文件，
地址是公开的下载地址（有效期约一年），NAS 直接下载就行，不用登录。
下载到 templates_lazada/lazada_auto_NNN.xlsx（和你自己上传的模板放一起；同一类目以最新的模板为准）。

★ 对外：status()  download_all(progress=None, force=False)  start_background()
"""
import json
import os
import threading
import time
import zipfile

from .config import BASE_DIR, DATA_DIR

INDEX_PATH = os.path.join(BASE_DIR, "core", "data", "lazada_templates.json")
STATE_PATH = os.path.join(DATA_DIR, "lazada_templates_state.json")
_lock = threading.Lock()
_running = {"on": False, "done": 0, "total": 0, "error": "", "current": ""}


def _index():
    try:
        with open(INDEX_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"files": []}


def _state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"done": {}, "errors": {}}


def _save_state(st):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_PATH + ".tmp", "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(STATE_PATH + ".tmp", STATE_PATH)


def _fname(i):
    return f"lazada_auto_{i:03d}.xlsx"


def _deleted_names():
    """在「管理模板」里删掉的自动模板：不自动再下载（「重新下载全部」才会）。"""
    from . import categories
    try:
        return {n.split("_", 2)[-1] for n in os.listdir(os.path.join(categories.TEMPLATE_DIR, "_deleted"))}
    except OSError:
        return set()


def status():
    from . import categories
    idx = _index()
    st = _state()
    files = idx.get("files") or []
    have = sum(1 for i, _x in enumerate(files) if os.path.exists(os.path.join(categories.TEMPLATE_DIR, _fname(i))))
    tree = categories.tree()
    lib = categories.library() if not _running["on"] and not categories._lib_lock.locked() else (categories._lib_memo["val"] or [])
    return {"files": len(files), "downloaded": have, "categories_total": len([1 for _k, (_p, d) in tree.items() if not d]),
            "categories_with_template": len(lib) if lib else None, "generated_at": idx.get("generated_at"),
            "expires_at": idx.get("expires_at"), "running": dict(_running), "parsing": categories._lib_lock.locked(), "errors": list((st.get("errors") or {}).values())[:5]}


def _download(url, dest, timeout=90):
    import requests
    r = requests.get(url, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}" + ("（地址过期了，需要重新生成模板地址）" if r.status_code in (403, 404) else ""))
    tmp = dest + ".part"
    with open(tmp, "wb") as f:
        f.write(r.content)
    try:
        with zipfile.ZipFile(tmp) as z:
            if not any(n.startswith("xl/") for n in z.namelist()):
                raise RuntimeError("下载的不是 Excel 文件")
    except zipfile.BadZipFile as e:
        os.remove(tmp)
        raise RuntimeError("下载的不是 Excel 文件") from e
    os.replace(tmp, dest)


def download_all(progress=None, force=False):
    """下载清单里还没有的模板（force=True 全部重新下载）。返回 {downloaded, skipped, failed}。"""
    from . import categories
    with _lock:
        if _running["on"]:
            raise RuntimeError("正在下载中")
        _running.update(on=True, done=0, error="", current="")
    try:
        files = _index().get("files") or []
        _running["total"] = len(files)
        st = _state()
        os.makedirs(categories.TEMPLATE_DIR, exist_ok=True)
        deleted = set() if force else _deleted_names()
        got = skipped = 0
        failed = []
        for i, x in enumerate(files):
            dest = os.path.join(categories.TEMPLATE_DIR, _fname(i))
            _running.update(done=i, current=_fname(i))
            if progress:
                progress(i, len(files))
            if (os.path.exists(dest) or _fname(i) in deleted) and not force:
                skipped += 1
                continue
            for attempt in range(3):
                try:
                    _download(x["url"], dest)
                    st.setdefault("done", {})[_fname(i)] = time.time()
                    st.setdefault("errors", {}).pop(_fname(i), None)
                    got += 1
                    break
                except Exception as e:  # noqa: BLE001
                    if attempt == 2:
                        st.setdefault("errors", {})[_fname(i)] = f"{_fname(i)}：{str(e)[:150]}"
                        failed.append(_fname(i))
                    else:
                        time.sleep(3)
            if i % 10 == 0:
                _save_state(st)
        _save_state(st)
        _running.update(done=len(files), current="")
        if got:
            threading.Thread(target=categories.library, daemon=True).start()   # 先把新模板解析好（缓存到硬盘）
        return {"downloaded": got, "skipped": skipped, "failed": failed, "total": len(files)}
    except Exception as e:  # noqa: BLE001
        _running["error"] = str(e)[:200]
        raise
    finally:
        _running["on"] = False


def start_background():
    """开机后：清单里还有没下载的模板就在后台下载（不影响使用）。"""
    from . import categories
    if os.environ.get("LH_NO_TPL_SYNC"):
        return

    def go():
        time.sleep(20)
        files = _index().get("files") or []
        deleted = _deleted_names()
        missing = [i for i in range(len(files)) if not os.path.exists(os.path.join(categories.TEMPLATE_DIR, _fname(i))) and _fname(i) not in deleted]
        if not missing:
            return
        try:
            download_all()
        except Exception:  # noqa: BLE001  联网失败等：页面上可以手动重试
            pass
    threading.Thread(target=go, daemon=True, name="lazada-templates").start()
