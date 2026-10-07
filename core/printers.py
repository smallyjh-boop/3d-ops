"""打印机连接：读取状态、发送文件开始打印、暂停/继续/取消。

支持三种连接方式（「自动」会按顺序试）：
- bambu      拓竹 Bambu Lab（P1S 等）局域网：MQTT 8883 读状态和下指令，FTPS 990 传文件。
             需要打印机屏幕上的「访问码」和序列号；新固件需要在打印机上打开「局域网模式」+「开发者模式」。
- moonraker  Creality K1 系列 root 后装了 Fluidd/Mainsail（Klipper Moonraker 接口，端口 7125 / 4408 / 4409）。
- creality   Creality K1 系列原厂固件（Creality Print 用的局域网接口，WebSocket 9999）。读状态可用；
             传文件（HTTP 上传）是按 Creality Print 的做法写的，需要在你的打印机上实测。
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
_status = {}          # 打印机序号 → 状态
_lock = threading.Lock()
_bambu = {}           # 序号 → BambuLink
_events = []          # 状态变化回调 (idx, old, new)


def on_change(fn):
    _events.append(fn)


def conn_cfg(p):
    c = dict(p.get("conn") or {})
    c.setdefault("type", "none")
    return c


def _set(idx, st):
    st["updated"] = time.time()
    with _lock:
        old = _status.get(idx) or {}
        _status[idx] = st
    if old.get("state") != st.get("state"):
        from . import db
        for fn in _events:
            try:
                fn(idx, old, st)
            except Exception:  # 回调出错不影响读取
                import traceback
                traceback.print_exc()
            finally:
                db.release()


def mark_sent(idx, name):
    """刚发送：先当作打印中（下一次读取前），这样打完时能识别出是这一盘。"""
    with _lock:
        st = dict(_status.get(idx) or {})
        st.update(state="printing", file=name, progress=0, updated=time.time())
        _status[idx] = st


def reset_status():
    """打印机列表改了（序号变了）：清空缓存的状态，下一轮重新读取。"""
    with _lock:
        _status.clear()


def get_status(idx=None):
    with _lock:
        if idx is None:
            return dict(_status)
        return dict(_status.get(idx) or {})


def _hex_from_bambu(c):
    c = (c or "").strip()
    return "#" + c[:6].lower() if len(c) >= 6 else ""


# ---------------- 拓竹 ----------------
class BambuLink:
    def __init__(self, idx, host, serial, code):
        self.idx, self.host, self.serial, self.code = idx, host, serial.strip(), code.strip()
        self.raw = {}
        self.stop = threading.Event()
        self.client = None
        self.error = ""
        self.thread = threading.Thread(target=self._run, daemon=True, name=f"bambu-{idx}")
        self.thread.start()

    def _run(self):
        while not self.stop.is_set():
            try:
                self.client = net.MiniMQTT(self.host, 8883, "bblp", self.code)
                self.client.on_message = self._msg
                self.client.connect()
                self.client.subscribe(f"device/{self.serial}/report")
                self.pushall()
                self.error = ""
                t = threading.Thread(target=self._periodic, daemon=True)
                t.start()
                self.client.loop(self.stop)
            except Exception as e:  # 断线重连
                self.error = str(e) or type(e).__name__
                _set(self.idx, {"state": "offline", "error": self.error, "conn": "bambu"})
            finally:
                try:
                    self.client and self.client.close()
                except Exception:  # 已断开
                    pass
            self.stop.wait(15)

    def _periodic(self):
        while not self.stop.is_set() and self.client and self.client.connected:
            self.stop.wait(300)
            try:
                self.pushall()
            except Exception:  # 下次重连
                return

    def pushall(self):
        self.publish({"pushing": {"sequence_id": "0", "command": "pushall"}})

    def publish(self, payload):
        if not self.client or not self.client.connected:
            raise ConnectionError("打印机还没连上")
        self.client.publish(f"device/{self.serial}/request", payload)

    def _msg(self, topic, payload):
        try:
            d = json.loads(payload)
        except ValueError:
            return
        p = d.get("print")
        if not isinstance(p, dict):
            return
        for k, v in p.items():          # P1 系列只推送变化的部分，合并
            if k == "ams" and isinstance(v, dict) and isinstance(self.raw.get("ams"), dict):
                self.raw["ams"].update(v)
            else:
                self.raw[k] = v
        _set(self.idx, self.normalize())

    def normalize(self):
        r = self.raw
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

    def command(self, cmd):
        self.publish({"print": {"sequence_id": str(int(time.time())), "command": cmd}})

    def start(self, local_path, remote_name, plate=1, ams_slot=None):
        net.bambu_upload(self.host, self.code, local_path, remote_name)
        use_ams = ams_slot is not None and ams_slot != 254
        self.publish({"print": {
            "sequence_id": str(int(time.time())), "command": "project_file",
            "param": f"Metadata/plate_{plate}.gcode", "url": f"file:///sdcard/{remote_name}",
            "subtask_name": os.path.splitext(remote_name)[0], "project_id": "0", "profile_id": "0", "task_id": "0",
            "subtask_id": "0", "md5": "", "timelapse": False, "bed_type": "auto", "bed_levelling": True,
            "flow_cali": False, "vibration_cali": False, "layer_inspect": False,
            "use_ams": use_ams, "ams_mapping": [int(ams_slot)] if use_ams else []}})

    def close(self):
        self.stop.set()
        try:
            self.client and self.client.close()
        except Exception:  # 已断开
            pass


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
    d = requests.get(f"{base}/printer/objects/query?{q}", timeout=5).json()["result"]["status"]
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


def creality_status(host):
    d = creality_raw(host)
    stt = d.get("state")
    prog = d.get("printProgress")
    st = {0: "idle", 1: "printing", 2: "finished", 3: "failed", 4: "failed", 5: "paused"}.get(stt, "unknown")
    if st == "unknown" and d:
        st = "printing" if prog not in (None, 0, 100) else "idle"
    left = d.get("printLeftTime")
    return {"state": st, "state_raw": str(stt), "progress": prog, "file": d.get("printFileName") or "",
            "remaining_min": round(left / 60) if isinstance(left, (int, float)) else None,
            "layer": d.get("layer"), "total_layers": d.get("TotalLayer"), "nozzle": d.get("nozzleTemp"),
            "bed": d.get("bedTemp0"), "error": str(d.get("err") or "") if d.get("err") not in (None, 0, "0", {}) else "",
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
    raise ValueError("连不上这个 IP。请确认打印机开机、和 NAS/电脑在同一个局域网，IP 没填错")


def _type(c):
    t = c.get("type") or "none"
    if t == "auto":
        t = c.get("detected") or "none"
    return t


def poll_once(idx, p):
    c = conn_cfg(p)
    t = _type(c)
    if t == "none":
        _set(idx, {"state": "none", "conn": "none"})
        return
    if t == "bambu":
        link = _bambu.get(idx)
        key = (c.get("host"), c.get("serial"), c.get("access_code"))
        if not link or (link.host, link.serial, link.code) != key:
            if link:
                link.close()
            _bambu[idx] = BambuLink(idx, *key)
        return
    try:
        if t == "moonraker":
            base = _mr_base(c)
            if not base:
                raise ConnectionError("Moonraker 没有回应")
            _set(idx, moonraker_status(base))
        elif t == "creality":
            _set(idx, creality_status(c["host"]))
    except Exception as e:  # 打印机关机等
        _set(idx, {"state": "offline", "error": str(e) or type(e).__name__, "conn": t})


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
        link = BambuLink.__new__(BambuLink)
        link.raw = got
        return t, link.normalize()
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
        link = _bambu.get(idx)
        if not link:
            raise ConnectionError("打印机还没连上")
        link.command(cmd)
    elif t == "moonraker":
        base = _mr_base(c)
        requests.post(f"{base}/printer/print/{'cancel' if cmd == 'stop' else cmd}", timeout=8).raise_for_status()
    elif t == "creality":
        params = {"pause": {"pause": 1}, "resume": {"pause": 0}, "stop": {"stop": 1}}[cmd]
        creality_raw(c["host"], wait=1, send={"method": "set", "params": params})
    else:
        raise ValueError("这台打印机没有设置连接")


def send_file(idx, local_path, remote_name, kind, ams_slot=None):
    """传文件并开始打印。返回打印机上的文件名。"""
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
            link = _bambu.get(idx)
            if not link or not link.client or not link.client.connected:
                raise ConnectionError("拓竹打印机还没连上（检查 IP / 访问码 / 局域网模式）")
            name = remote_name if remote_name.endswith(".3mf") else remote_name + ".gcode.3mf"
            link.start(local_path, name, 1, ams_slot)
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
        raise ValueError("这台打印机没有设置连接（打印机页 → 连接设置）")
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


# ---------------- 后台轮询 ----------------
_started = False


def _loop():
    while True:
        try:
            cfg = load_config()
            printers = cfg.get("printers") or []
            for i, p in enumerate(printers):
                poll_once(i, p)
            for i in list(_bambu):
                if i >= len(printers) or _type(conn_cfg(printers[i])) != "bambu":
                    _bambu.pop(i).close()
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            from . import db
            db.release()
        time.sleep(10)


def start():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="printer-poll").start()
