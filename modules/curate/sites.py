"""站点包（从「3D选品工具」搬过来）：哪个模型网站怎么认链接、怎么读详情页、怎么搜索、怎么换真实下载地址——全是数据（JSON），不含代码。

  模块自带：modules/curate/sites/*.json（随 ERP 升级更新）
  自己改 / 新加：data/curate/sites/*.json（同一个 id 覆盖自带的；不用升级扩展，也不用升级 ERP）
扩展每 10 分钟问一次 GET /api/v1/curate/ext/sites，版本（内容指纹）变了就换成新规则。
"""
import glob
import hashlib
import json
import os
import re
from urllib.parse import quote, unquote, urlparse

from core.config import DATA_DIR

HERE = os.path.join(os.path.dirname(__file__), "sites")
USER_DIR = os.path.join(DATA_DIR, "curate", "sites")
_memo = {"key": None, "sites": {}}


def _files():
    out = {}
    for d in (HERE, USER_DIR):
        for p in sorted(glob.glob(os.path.join(d, "*.json"))):
            out[os.path.basename(p)] = p          # data 里同名的覆盖自带的
    return list(out.values())


def load():
    """{站点 id: 站点包}（带编译好的正则 _rx）。文件没变就用上次的。"""
    files = _files()
    key = tuple((p, os.path.getmtime(p)) for p in files)
    if _memo["key"] == key:
        return _memo["sites"]
    sites = {}
    for p in files:
        try:
            with open(p, encoding="utf-8") as f:
                s = json.load(f)
            s["_rx"] = re.compile(s["detail"]["path"], re.I)
        except (OSError, ValueError, KeyError, re.error):
            continue
        sites[s["id"]] = s
    _memo.update(key=key, sites=sites)
    return sites


def public_list():
    """给扩展的：去掉内部字段 + 版本（内容指纹）。"""
    sites = [{k: v for k, v in s.items() if not k.startswith("_")} for s in load().values()]
    raw = json.dumps(sites, ensure_ascii=False, sort_keys=True)
    return {"version": hashlib.sha1(raw.encode()).hexdigest()[:12], "sites": sites}


def _host_in(host, domains):
    host = (host or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains or [])


def site_for_url(url):
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return None
    for s in load().values():
        if s.get("enabled", True) and _host_in(host, s.get("domains")):
            return s
    return None


def _match(url):
    s = site_for_url(url)
    if not s:
        return None, None
    try:
        path = unquote(urlparse(url).path)
    except ValueError:
        return s, None
    return s, s["_rx"].search(path)


def canonical(url):
    """原站模型详情页的标准地址（去掉参数、锚点）；不是详情页返回 ""。"""
    url = (url or "").strip()
    s, m = _match(url)
    if not m or urlparse(url).scheme != "https":
        return ""
    return f"https://{(urlparse(url).hostname or '').lower()}{m.group(1)}"


def source_key(url):
    """同一个原站模型的不同链接算同一个：mw:12345 / pr:12345 / tv:12345。"""
    s, m = _match((url or "").strip())
    if not m:
        return ""
    return f"{s['key_prefix']}:{m.group(int(s['detail'].get('id_group', 2)))}"


def source_id(url):
    k = source_key(url)
    return k.split(":", 1)[1] if k else ""


def platform(url):
    s = site_for_url(url)
    return s["id"] if s else "other"


def name_of(pid):
    s = load().get(pid)
    return s["name"] if s else ("其他网站" if pid in ("other", "") else pid)


def search_entries():
    """[(搜索编号, 名称, 地址模板含 {q})]"""
    out = []
    for s in load().values():
        if s.get("enabled", True):
            for e in s.get("search") or []:
                out.append((e["id"], e.get("label") or s["name"], e["url"]))
    return out


def search_url(entry_id, q):
    tpl = {k: u for k, _n, u in search_entries()}.get(entry_id)
    if not tpl:
        raise ValueError("请选择在哪个网站搜索")
    return tpl.replace("{q}", quote(q))


def domains():
    return sorted({d for s in load().values() if s.get("enabled", True) for d in s.get("domains") or []})


def builtin_js():
    """扩展自带的默认规则 extension/cur_sites_builtin.js 的内容（只用模块自带的站点包）。"""
    sites = []
    for p in sorted(glob.glob(os.path.join(HERE, "*.json"))):
        with open(p, encoding="utf-8") as f:
            sites.append(json.load(f))
    return ("// 随扩展带的默认站点规则（由 modules/curate/sites/*.json 生成：python -m modules.curate.sites）。连上 ERP 后用 ERP 发来的最新规则。\n"
            "globalThis.__CURATOR_SITES_BUILTIN = " + json.dumps({"sites": sites}, ensure_ascii=False) + ";\n")


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.dirname(HERE)), "..", "extension", "cur_sites_builtin.js")
    with open(os.path.normpath(out), "w", encoding="utf-8") as f:
        f.write(builtin_js())
    print("written", os.path.normpath(out))
