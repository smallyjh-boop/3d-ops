"""外网自动加入（Tailscale）的接口。"""
import json
import os
import re
import threading
import time
from urllib.parse import urlparse

from flask import Blueprint, g, jsonify, request

from core import db
from core.config import DATA_DIR, load_config

bp = Blueprint("m_tailscale", __name__)
PREFIXES = ["/api/v1/accel/tailscale"]          # 模块关掉时这些接口也一起关（/api/m/tailscale/ 自动算）
STATE = os.path.join(DATA_DIR, "tailscale_joins.json")
_lock = threading.Lock()


def _joins():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _nas_target(cfg):
    u = str(cfg.get("remote_url") or "")
    p = urlparse(u if "://" in u else "http://" + u) if u else None
    host = (p.hostname if p else "") or "100.x.y.z"
    port = (p.port if p else None) or int(os.environ.get("PORT") or 8790)
    return host, port


def acl_policy(cfg=None):
    """给老板复制到 Tailscale 后台「Access controls」的访问规则：自己的设备照常全通，打了标签的员工电脑只能访问 NAS 上这个系统。"""
    cfg = cfg or load_config()
    tag = cfg.get("ts_tag") or "tag:3dops"
    host, port = _nas_target(cfg)
    return ('{\n'
            '  // 3D 运营管理系统：员工电脑（' + tag + '）只能访问 NAS 上的系统\n'
            '  "tagOwners": {\n'
            '    "' + tag + '": ["autogroup:admin"],\n'
            '  },\n'
            '  "acls": [\n'
            '    // 你自己账号的设备：和以前一样全部互通\n'
            '    {"action": "accept", "src": ["autogroup:member"], "dst": ["*:*"]},\n'
            '    // 员工电脑：只能打开 NAS 上的 3D 运营管理系统\n'
            '    {"action": "accept", "src": ["' + tag + '"], "dst": ["' + host + ':' + str(port) + '"]},\n'
            '  ],\n'
            '}\n')


@bp.get("/api/m/tailscale/status")
def ts_status():
    cfg = load_config()
    key = str(cfg.get("ts_authkey") or "")
    host, port = _nas_target(cfg)
    js = _joins()
    return jsonify({"key_set": bool(key), "key_ok": key.startswith("tskey-"), "tag": cfg.get("ts_tag") or "tag:3dops",
                    "auto": bool(cfg.get("ts_auto")), "remote_url": cfg.get("remote_url") or "", "nas": f"{host}:{port}",
                    "acl": acl_policy(cfg), "joins": sorted(js.values(), key=lambda x: -x.get("at", 0))[:50]})


def _worker_name():
    from core import desktop
    u = getattr(g, "user", None) or {}
    return desktop.describe_key(str(u.get("display_name") or ""))


@bp.get("/api/v1/accel/tailscale")
def ts_info():
    """桌面客户端 / 加速器用自己的电脑加速密钥来拿预授权密钥。"""
    cfg = load_config()
    key = str(cfg.get("ts_authkey") or "").strip()
    if not key:
        return jsonify({"error": "NAS 上还没有填 Tailscale 预授权密钥（设置 → 通用 → 外网自动加入）"}), 404
    db.audit(f"api:{_worker_name()}", "取 Tailscale 预授权密钥", request.remote_addr or "")
    return jsonify({"authkey": key, "tag": cfg.get("ts_tag") or "tag:3dops", "auto": bool(cfg.get("ts_auto")),
                    "remote_url": cfg.get("remote_url") or ""})


@bp.post("/api/v1/accel/tailscale/joined")
def ts_joined():
    b = request.get_json(silent=True) or {}
    name = _worker_name()
    ips = [str(x)[:40] for x in (b.get("ips") or []) if re.fullmatch(r"[0-9a-fA-F.:]+", str(x))][:4]
    with _lock:
        d = _joins()
        d[name] = {"name": name, "ok": bool(b.get("ok")), "ips": ips, "msg": str(b.get("msg") or "")[:300], "at": time.time()}
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(STATE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(STATE + ".tmp", STATE)
    return jsonify({"ok": True})
