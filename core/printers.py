"""打印机连接：读取状态、发送文件开始打印、暂停/继续/取消。

支持三种连接方式（「自动」会按顺序试）：
- bambu      拓竹 Bambu Lab（P1S 等）局域网：MQTT 8883 读状态和下指令，FTPS 990 传文件。
             需要打印机屏幕上的「访问码」和序列号；新固件需要在打印机上打开「局域网模式」+「开发者模式」。
- moonraker  Creality K1 系列 root 后装了 Fluidd/Mainsail（Klipper Moonraker 接口，端口 7125 / 4408 / 4409）。
- creality   Creality K1 系列原厂固件（Creality Print 用的局域网接口，WebSocket 9999）。读状态可用；
             传文件（HTTP 上传）是按 Creality Print 的做法写的，需要在你的打印机上实测。
v2.54：连接由 core/printer_manager.py 管（一个事件循环管几千台，不再一台一个线程）；对外的函数不变：
get_status / command / send_file / test / match_tray / loaded_colors / on_change。状态缓存仍按序号（_status）。
"""
import json
import os
import tempfile
import threading
import time

import requests

from . import printer_net as net
from .config import load_config

STATE_ZH = {"idle": "空闲", "printing": "打印中", "paused": "已暂停", "finished": "打印完成", "failed": "失败/已取消",
            "offline": "连不上", "unknown": "未知", "none": "未连接"}
_lock = threading.Lock()
_events = []          # 状态变化回调 (idx, old, new)
_mgr = None           # v2.54 连接管理（core/printer_manager.py）：一个事件循环管所有打印机
_remote = {"on": False, "at": 0.0, "marks": {}}   # 后台进程模式：从数据库读状态
_MAPS = {"key": None, "p2i": {}, "i2p": {}}


class UnknownResult(ConnectionError):
    """v2.54 复审：指令交给后台进程后 ERP 等不到结果，但后台进程已经在执行 / 执行完了 —— 结果未知，不能当成失败（会重发 → 打两盘）。"""


def maps():
    """打印机稳定 id ↔ 现在的序号。按设置文件的版本缓存（别的进程改了设置也马上认出来），删了打印机马上生效，
    不用等连接管理下一次对设置。测试里连接管理用自己的设置（cfg_loader）时用它最近一次对到的。"""
    if _mgr is not None and getattr(_mgr, "cfg_loader", None) is not None:
        return _mgr.idmap, _mgr.idxmap
    from . import config as _c
    key = (_c.file_key(), _c._CACHE["gen"])
    if _MAPS["key"] != key:
        prs = _c.load_config().get("printers") or []
        p2i = {}
        for i, p in enumerate(prs):
            p2i[p.get("id") or f"#{i}"] = i
        _MAPS.update(key=key, p2i=p2i, i2p={i: k for k, i in p2i.items()})
    return _MAPS["p2i"], _MAPS["i2p"]


def pid_of(idx):
    """序号 → 稳定 id（找不到时用 #序号）。"""
    if isinstance(idx, str):
        return idx
    return maps()[1].get(idx, f"#{idx}")


def index_of(pid):
    """稳定 id → 现在的序号（打印机已经删掉了 → None）。"""
    if isinstance(pid, int):
        return pid
    i = maps()[0].get(pid)
    if i is None and isinstance(pid, str) and pid.startswith("#") and pid[1:].isdigit():
        return int(pid[1:])
    return i


class _Status:
    """v2.54 复审：状态缓存按稳定 id 存（以前按序号存：删了一台以后，连接管理还没对设置前收到的状态会写到别的打印机上）。
    外面照旧可以按序号读写（_status[0] = …），按序号时用设置里现在的顺序换成 id。"""

    def __init__(self):
        self.d = {}

    def _k(self, key):
        return pid_of(key) if isinstance(key, int) else key

    def __getitem__(self, key):
        return self.d[self._k(key)]

    def __setitem__(self, key, val):
        self.d[self._k(key)] = val

    def __contains__(self, key):
        return self._k(key) in self.d

    def get(self, key, default=None):
        return self.d.get(self._k(key), default)

    def pop(self, key, default=None):
        return self.d.pop(self._k(key), default)

    def clear(self):
        self.d.clear()

    def __len__(self):
        return len(self.d)

    def by_index(self):
        """{序号: 状态}（按现在的顺序；已经删掉的打印机不出现）。"""
        out = {}
        for k, v in list(self.d.items()):
            i = index_of(k)
            if i is not None:
                out[i] = v
        return out

    def items(self):
        return self.by_index().items()

    def values(self):
        return self.by_index().values()

    def keys(self):
        return self.by_index().keys()


_status = _Status()   # 稳定 id → 状态


def on_change(fn):
    _events.append(fn)


def conn_cfg(p):
    c = dict(p.get("conn") or {})
    c.setdefault("type", "none")
    return c


def _store(key, st):
    """只记状态，返回 (旧状态, 状态是否变了)。key = 稳定 id（连接管理 / 后台进程）或序号。通知由调用的人决定。"""
    st["updated"] = st.get("updated") or time.time()
    with _lock:
        old = _status.get(key) or {}
        _status[key] = st
    return old, old.get("state") != st.get("state")


def _fire(idx, old, st):
    from . import db
    for fn in _events:
        try:
            fn(idx, old, st)
        except Exception:  # 回调出错不影响读取
            import traceback
            traceback.print_exc()
        finally:
            db.release()


def fire_pid(pid, old, st):
    """状态变化通知：通知时才把 id 换成现在的序号（排队期间删了 / 挪了打印机也不会通知到别的打印机上）。"""
    i = index_of(pid)
    if i is None:
        return False
    _fire(i, old, st)
    return True


def _set(idx, st):
    st["updated"] = time.time()
    pid = pid_of(idx)
    old, changed = _store(pid, st)
    if changed:
        fire_pid(pid, old, st)


def mark_sent(idx, name):
    """刚发送：先当作打印中（下一次读取前），这样打完时能识别出是这一盘。"""
    pid = pid_of(idx)
    with _lock:
        st = dict(_status.get(pid) or {})
        st.update(state="printing", file=name, progress=0, updated=time.time())
        _status[pid] = st
        _remote["marks"][pid] = st["updated"]


def reset_status():
    """打印机列表改了（序号变了）：清空缓存的状态，下一轮重新读取。"""
    with _lock:
        _status.clear()
    if _mgr:
        _mgr.kick()


def remap_status(mapping):
    """删了打印机、序号变了：状态按稳定 id 存，自动跟着打印机走；只有没有 id 的（#序号）按 mapping 挪。"""
    with _lock:
        for k in [k for k in _status.d if isinstance(k, str) and k.startswith("#") and k[1:].isdigit()]:
            i = int(k[1:])
            st = _status.d.pop(k)
            j = mapping.get(i, i)
            if j is not None:
                _status.d[f"#{j}"] = st
    if _mgr:
        _mgr.kick()


def get_status(idx=None):
    if _remote["on"]:
        _pull_remote()
    with _lock:
        if idx is None:
            return {i: dict(v) for i, v in _status.by_index().items()}
        return dict(_status.get(idx) or {})


# ---------------- 后台进程模式（PRINTER_WORKER=external）：ERP 从数据库读状态、把指令交给后台进程 ----------------
def _pull_remote(force=False):
    if not force and time.time() - _remote["at"] < 1.0:
        return
    _remote["at"] = time.time()
    from . import db, printer_manager
    try:
        c = db.conn()
        printer_manager.ensure_tables(c)
        rows = c.execute("SELECT pid, idx, data, updated FROM printer_state").fetchall()
    except Exception:  # noqa: BLE001  数据库忙：下次再读
        return
    local = set(_mgr.links) if _mgr else set()
    with _lock:
        for r in rows:
            pid = r["pid"]
            if pid in local:
                continue
            if (_remote["marks"].get(pid) or 0) > (r["updated"] or 0):
                continue           # 刚发送过：还没读到新状态前先当作打印中
            try:
                _status.d[pid] = json.loads(r["data"] or "{}")
            except ValueError:
                pass


REMOTE_WAIT = 12      # ERP 等后台进程执行指令最多几秒
UNKNOWN_MSG = "结果未知，请到打印机上确认，不要重发"


def _remote_call(p, op, payload=None, wait=None, key=""):
    """交给后台进程执行（拓竹的指令要走它一直连着的 MQTT），等结果。
    v2.54 复审：后台进程先「认领」指令（status new → running，只有一个进程能认领成功）再执行；
    ERP 等不到结果时：后台进程还没认领 → 改成 timeout（之后也不会再执行）→ 报失败；已经认领（running / done）→ 结果未知
    （UnknownResult，不能当失败，不然员工重发 → 打两盘）。key：幂等键，同一次发送（同一个 key）后台进程只执行一次。"""
    from . import db, printer_manager
    wait = REMOTE_WAIT if wait is None else wait
    c = db.conn()
    printer_manager.ensure_tables(c)
    cur = c.execute("INSERT INTO printer_cmds(pid, op, payload, status, created, ikey) VALUES(?,?,?, 'new', ?, ?)",
                    (p.get("id"), op, json.dumps(payload or {}, ensure_ascii=False), time.time(), key or ""))
    c.commit()
    cid = cur.lastrowid
    if not wait:
        return None

    def outcome(r):
        if r["status"] == "done":
            return True, r["result"]
        if r["status"] == "error":
            raise ConnectionError(r["result"] or "打印机后台进程执行失败")
        if r["status"] == "dup":
            raise UnknownResult("这次发送后台进程已经执行过了（同一次发送不会执行两次）：" + UNKNOWN_MSG)
        return False, None
    end = time.time() + wait
    while time.time() < end:
        r = c.execute("SELECT status, result FROM printer_cmds WHERE id=?", (cid,)).fetchone()
        if r:
            done, res = outcome(r)
            if done:
                return res
        time.sleep(0.2)
    n = c.execute("UPDATE printer_cmds SET status='timeout', done=? WHERE id=? AND status='new'", (time.time(), cid)).rowcount
    c.commit()
    if n:
        raise ConnectionError("打印机后台进程没有回应，指令没有执行（PRINTER_WORKER=external：确认 python -m core.printer_worker 在运行）")
    r = c.execute("SELECT status, result FROM printer_cmds WHERE id=?", (cid,)).fetchone()
    done, res = outcome(r)
    if done:
        return res
    raise UnknownResult("打印机后台进程已经在执行，但还没回结果：" + UNKNOWN_MSG)


def _link(idx, p):
    """这台打印机在本进程里的拓竹连接（没有返回 None）。"""
    if not _mgr:
        return None
    return _mgr.links.get(p.get("id") or f"#{idx}")


def _hex_from_bambu(c):
    c = (c or "").strip()
    return "#" + c[:6].lower() if len(c) >= 6 else ""


# ---------------- 拓竹 ----------------
def bambu_normalize(r):
    """拓竹 MQTT 推送（合并后的 print 部分）→ 统一的状态。"""
    gs = str(r.get("gcode_state") or "").upper()
    state = {"IDLE": "idle", "RUNNING": "printing", "PREPARE": "printing", "SLICING": "printing",
             "PAUSE": "paused", "FINISH": "finished", "FAILED": "failed"}.get(gs, "unknown")
    trays = []
    ams = r.get("ams") if isinstance(r.get("ams"), dict) else {}
    for unit in ams.get("ams") or []:
        for t in unit.get("tray") or []:
            if t.get("tray_type"):
                trays.append({"slot": int(unit.get("id", 0)) * 4 + int(t.get("id", 0)), "type": t.get("tray_type"),
                              "hex": _hex_from_bambu(t.get("tray_color")), "remain": t.get("remain"),
                              "label": f"AMS{int(unit.get('id', 0)) + 1}-{int(t.get('id', 0)) + 1}"})
    vt = r.get("vt_tray")
    if isinstance(vt, dict) and vt.get("tray_type"):
        trays.append({"slot": 254, "type": vt.get("tray_type"), "hex": _hex_from_bambu(vt.get("tray_color")),
                      "remain": vt.get("remain"), "label": "外挂料盘"})
    err = r.get("print_error") or 0
    return {"state": state, "state_raw": gs, "progress": r.get("mc_percent"),
            "remaining_min": r.get("mc_remaining_time"), "file": r.get("subtask_name") or r.get("gcode_file") or "",
            "layer": r.get("layer_num"), "total_layers": r.get("total_layer_num"),
            "nozzle": r.get("nozzle_temper"), "bed": r.get("bed_temper"), "trays": trays,
            "tray_now": ams.get("tray_now"), "error": f"错误码 {err}" if err else "", "conn": "bambu"}


def bambu_start_payload(remote_name, plate=1, ams_slot=None):
    use_ams = ams_slot is not None and ams_slot != 254
    return {"print": {
        "sequence_id": str(int(time.time())), "command": "project_file",
        "param": f"Metadata/plate_{plate}.gcode", "url": f"file:///sdcard/{remote_name}",
        "subtask_name": os.path.splitext(remote_name)[0], "project_id": "0", "profile_id": "0", "task_id": "0",
        "subtask_id": "0", "md5": "", "timelapse": False, "bed_type": "auto", "bed_levelling": True,
        "flow_cali": False, "vibration_cali": False, "layer_inspect": False,
        "use_ams": use_ams, "ams_mapping": [int(ams_slot)] if use_ams else []}}


# ---------------- Moonraker（root 过的 K1）----------------
def _mr_base(c):
    host = c.get("host", "").strip()
    ports = [c["port"]] if c.get("port") else [7125, 4408, 4409]
    for port in ports:
        try:
            r = requests.get(f"http://{host}:{port}/server/info", timeout=3)
            if r.ok and "result" in r.json():
                return f"http://{host}:{port}"
        except (requests.RequestException, ValueError):
            continue
    return None


def moonraker_status(base):
    q = "print_stats&display_status&extruder&heater_bed&virtual_sdcard"
    return moonraker_normalize(requests.get(f"{base}/printer/objects/query?{q}", timeout=5).json()["result"]["status"])


def moonraker_normalize(d):
    ps = d.get("print_stats") or {}
    st = {"standby": "idle", "printing": "printing", "paused": "paused", "complete": "finished",
          "cancelled": "failed", "error": "failed"}.get(ps.get("state"), "unknown")
    prog = (d.get("display_status") or {}).get("progress") or (d.get("virtual_sdcard") or {}).get("progress") or 0
    dur = ps.get("print_duration") or 0
    remain = (dur / prog - dur) / 60 if prog > 0.01 and st == "printing" else None
    info = ps.get("info") or {}
    return {"state": st, "state_raw": ps.get("state"), "progress": round(prog * 100), "file": ps.get("filename") or "",
            "remaining_min": round(remain) if remain else None, "layer": info.get("current_layer"),
            "total_layers": info.get("total_layer"), "nozzle": (d.get("extruder") or {}).get("temperature"),
            "bed": (d.get("heater_bed") or {}).get("temperature"), "error": ps.get("message") or "", "trays": [],
            "conn": "moonraker"}


# ---------------- Creality 原厂固件 ----------------
def creality_raw(host, wait=2.5, send=None):
    s = net.ws_connect(host, 9999)
    try:
        if send:
            net.ws_send(s, json.dumps(send))
        s.settimeout(1.0)
        data, end = {}, time.time() + wait
        while time.time() < end:
            try:
                msg = net.ws_recv(s)
            except OSError:
                continue
            try:
                m = json.loads(msg)
            except ValueError:
                continue
            if isinstance(m, dict):
                data.update(m)
        return data
    finally:
        net.ws_close(s)


def _creality_err(err):
    """v2.53：Creality 原厂固件的 err 是 {'errcode': 0, 'key': 0, 'value': ''}，errcode 为 0 表示没有错误（以前原样显示成红字）。"""
    if err in (None, 0, "0", "", {}):
        return ""
    if isinstance(err, dict):
        code = err.get("errcode") or err.get("key") or 0
        try:
            code = int(code)
        except (TypeError, ValueError):
            pass
        if not code:
            return ""
        val = str(err.get("value") or "").strip()
        return f"错误码 {code}" + (f"：{val}" if val else "")
    return str(err)


def creality_status(host):
    return creality_normalize(creality_raw(host))


def creality_normalize(d):
    stt = d.get("state")
    prog = d.get("printProgress")
    st = {0: "idle", 1: "printing", 2: "finished", 3: "failed", 4: "failed", 5: "paused"}.get(stt, "unknown")
    if st == "unknown" and d:
        st = "printing" if prog not in (None, 0, 100) else "idle"
    left = d.get("printLeftTime")
    return {"state": st, "state_raw": str(stt), "progress": prog, "file": d.get("printFileName") or "",
            "remaining_min": round(left / 60) if isinstance(left, (int, float)) else None,
            "layer": d.get("layer"), "total_layers": d.get("TotalLayer"), "nozzle": d.get("nozzleTemp"),
            "bed": d.get("bedTemp0"), "error": _creality_err(d.get("err")),
            "trays": [], "conn": "creality"}


# ---------------- 统一入口 ----------------
def detect(c):
    """自动识别连接方式。"""
    host = (c.get("host") or "").strip()
    if not host:
        raise ValueError("请填写打印机的 IP 地址")
    if c.get("serial") and c.get("access_code"):
        if net.port_open(host, 8883):
            return "bambu"
    if _mr_base(c):
        return "moonraker"
    if net.port_open(host, 9999):
        return "creality"
    if net.port_open(host, 8883):
        raise ValueError("这是拓竹打印机：请填写序列号和访问码（打印机屏幕 设置 → 网络/WLAN）")
    from . import netdiag
    raise ValueError(netdiag.fail_message(host))


def _human_err(e):
    """v2.41：网络错误换成员工看得懂的中文（泰文界面会翻译），不再显示 [Errno 111] Connection refused。"""
    s = str(e) or type(e).__name__
    low = s.lower()
    if "refused" in low or "errno 111" in low or "10061" in low:
        return "打印机拒绝连接（打印机开着吗？局域网模式 / 访问码对吗？）"
    if "timed out" in low or "timeout" in low:
        return "连不上打印机（超时）：检查打印机是否开机、IP 是否对、是否在同一个网络"
    if "no route" in low or "unreachable" in low or "errno 113" in low or "name or service" in low:
        return "找不到这台打印机（打印机关机了、IP 不对，或不在同一个网络）"
    return s


def _no_conn_msg(c):
    """v2.41：连接方式选了「自动识别」但还没认出来 → 说清楚，不是「没有设置连接」。"""
    if (c.get("type") or "none") == "auto":
        return ("这台打印机的连接方式是「自动识别」，但还没认出来是哪种（打印机没开 / IP 不通 / 不在同一个网络）。"
                "确认打印机开着、IP 对，或者在 打印机 → 连接设置 里手动选连接方式")
    return "这台打印机没有设置连接（打印机页 → 连接设置）"


def _type(c):
    t = c.get("type") or "none"
    if t == "auto":
        t = c.get("detected") or "none"
    return t


def poll_once(idx, p):
    """设置改了 / 点了测试：马上重新读这一台（v2.54 交给连接管理，不在网页请求里连打印机）。"""
    c = conn_cfg(p)
    t = _type(c)
    if t == "none":
        _set(idx, {"state": "none", "conn": "none"})
        return
    if _mgr:
        _mgr.kick(p.get("id") or f"#{idx}")
    elif _remote["on"]:
        try:
            _remote_call(p, "kick", wait=0)
        except Exception:  # noqa: BLE001
            pass


def test(p):
    """设置页「测试连接」：识别类型并读一次状态。"""
    c = conn_cfg(p)
    t = c.get("type") or "auto"
    if t in ("auto", "none"):
        t = detect(c)
    if t == "bambu":
        cl = net.MiniMQTT(c["host"], 8883, "bblp", c.get("access_code", ""))
        cl.connect()
        got = {}
        cl.on_message = lambda topic, msg: got.update(json.loads(msg).get("print") or {})
        cl.subscribe(f"device/{c.get('serial', '').strip()}/report")
        cl.publish(f"device/{c.get('serial', '').strip()}/request", {"pushing": {"sequence_id": "0", "command": "pushall"}})
        ev = threading.Event()
        threading.Timer(4, ev.set).start()
        try:
            cl.loop(ev)
        except Exception:  # 读到多少算多少
            pass
        cl.close()
        if not got:
            raise ValueError("连上了，但没收到打印机状态：请检查序列号是否正确")
        return t, bambu_normalize(got)
    if t == "moonraker":
        base = _mr_base(c)
        if not base:
            raise ValueError("Moonraker 没有回应（root 过的 K1 一般是端口 7125 或 4408）")
        return t, moonraker_status(base)
    if t == "creality":
        return t, creality_status(c["host"])
    raise ValueError("不支持的连接方式")


def command(idx, cmd):
    """暂停 pause / 继续 resume / 取消 stop"""
    cfg = load_config()
    p = (cfg.get("printers") or [])[idx]
    c = conn_cfg(p)
    t = _type(c)
    if t == "bambu":
        payload = {"print": {"sequence_id": str(int(time.time())), "command": cmd}}
        link = _link(idx, p)
        if link:
            _mgr.call(link.publish(payload))
        elif _remote["on"]:
            _remote_call(p, "publish", payload)
        else:
            raise ConnectionError("打印机还没连上")
    elif t == "moonraker":
        base = _mr_base(c)
        requests.post(f"{base}/printer/print/{'cancel' if cmd == 'stop' else cmd}", timeout=8).raise_for_status()
    elif t == "creality":
        params = {"pause": {"pause": 1}, "resume": {"pause": 0}, "stop": {"stop": 1}}[cmd]
        creality_raw(c["host"], wait=1, send={"method": "set", "params": params})
    else:
        raise ValueError(_no_conn_msg(c))


_SEND = threading.local()


class send_key:
    """with send_key("…"): send_file(…) —— 这次发送的幂等键（后台进程模式下同一个 key 只执行一次）。
    用 with 而不是参数：测试 / 别的地方替换 send_file 的写法不用改。"""

    def __init__(self, key):
        self.key = key

    def __enter__(self):
        self.prev = getattr(_SEND, "key", "")
        _SEND.key = self.key
        return self

    def __exit__(self, *a):
        _SEND.key = self.prev


def send_file(idx, local_path, remote_name, kind, ams_slot=None, key=None):
    """传文件并开始打印。返回打印机上的文件名。key：幂等键（不给就用 with send_key(…) 设的）。
    后台进程模式下结果未知时抛 UnknownResult（调用的人不能当成失败）。"""
    if key is None:
        key = getattr(_SEND, "key", "") or ""
    cfg = load_config()
    p = (cfg.get("printers") or [])[idx]
    c = conn_cfg(p)
    t = _type(c)
    st = get_status(idx)
    if st.get("state") in ("printing", "paused"):
        raise ValueError(f"「{p.get('name')}」正在打印，不能发送新文件")
    tmp = None
    try:
        if t == "bambu":
            if kind != "3mf":
                raise ValueError("拓竹打印机要用切片好的 .gcode.3mf 文件")
            link = _link(idx, p)
            if not _remote["on"] and (not link or not link.connected):
                raise ConnectionError("拓竹打印机还没连上（检查 IP / 访问码 / 局域网模式）")
            name = remote_name if remote_name.endswith(".3mf") else remote_name + ".gcode.3mf"
            net.bambu_upload(c["host"].strip(), c.get("access_code", "").strip(), local_path, name)
            payload = bambu_start_payload(name, 1, ams_slot)
            if link and link.connected:
                _mgr.call(link.publish(payload))
            else:
                _remote_call(p, "publish", payload, key=key)
            return name
        # Klipper / Creality 要 G-code
        if kind == "3mf":
            from . import print_files
            tmp = tempfile.NamedTemporaryFile(suffix=".gcode", delete=False).name
            print_files.gcode_from_3mf(local_path, tmp)
            local_path = tmp
        name = os.path.splitext(remote_name.replace(".gcode.3mf", ""))[0] + ".gcode"
        if t == "moonraker":
            base = _mr_base(c)
            if not base:
                raise ConnectionError("Moonraker 没有回应")
            with open(local_path, "rb") as f:
                r = requests.post(f"{base}/server/files/upload", files={"file": (name, f)}, data={"print": "true"}, timeout=300)
            r.raise_for_status()
            return name
        if t == "creality":
            with open(local_path, "rb") as f:
                r = requests.post(f"http://{c['host']}/upload/{name}", files={"file": (name, f)}, timeout=300)
            if r.status_code >= 400:
                raise ConnectionError(f"上传失败（{r.status_code}）。原厂固件可以先用 Creality Print 把文件传到打印机，再在这里开始")
            creality_raw(c["host"], wait=1, send={"method": "set",
                                                  "params": {"opGcodeFile": f"printprt:/usr/data/printer_data/gcodes/{name}"}})
            return name
        raise ValueError(_no_conn_msg(c))
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


# ---------------- 颜色 → 料盘 ----------------
def _rgb(h):
    h = (h or "").lstrip("#")
    if len(h) < 6:
        return None
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def match_tray(idx, color_hex, material=""):
    """在打印机的料盘里找最接近的颜色。返回 (槽位, 料盘, 距离)；没有料盘信息返回 None。"""
    trays = get_status(idx).get("trays") or []
    target = _rgb(color_hex)
    if not trays or not target:
        return None
    best = None
    for t in trays:
        rgb = _rgb(t.get("hex"))
        if not rgb:
            continue
        dist = sum((a - b) ** 2 for a, b in zip(rgb, target)) ** 0.5
        if material and t.get("type") and material.upper().split("-")[0] not in str(t["type"]).upper():
            dist += 80
        if best is None or dist < best[2]:
            best = (t["slot"], t, dist)
    return best


def loaded_colors(idx, p):
    """这台打印机现在装着的颜色（料盘读到的 + 手动填的）。"""
    out = [t.get("hex") for t in (get_status(idx).get("trays") or []) if t.get("hex")]
    return out, [x.strip() for x in str(conn_cfg(p).get("loaded") or "").replace("，", ",").split(",") if x.strip()]


# ---------------- 后台连接（v2.54：core/printer_manager.py 一个事件循环管所有打印机） ----------------
def start(worker=False, worker_id=None):
    """ERP 启动时调：默认在本进程里连打印机。PRINTER_WORKER=external：本进程不连，从数据库读后台进程写的状态。
    worker=True：自己就是后台进程（python -m core.printer_worker），状态写进数据库。"""
    global _mgr
    if _mgr:
        return _mgr
    wid = os.environ.get("PRINTER_WORKER_ID", "") if worker_id is None else worker_id
    if not worker and os.environ.get("PRINTER_WORKER") == "external":
        _remote["on"] = True
        return None
    from . import printer_manager
    _mgr = printer_manager.Manager(worker_id=wid, persist=worker).start()
    # 分组分给别的后台进程的打印机：从数据库读它们的状态
    try:
        from .config import load_config
        if load_config().get("printer_workers"):
            _remote["on"] = True
    except Exception:  # noqa: BLE001
        pass
    return _mgr


def manager():
    return _mgr
