"""打印机连接管理（v2.54，几百到几千台打印机）：一个事件循环（asyncio）管所有连接，不再一台拓竹一个线程。

- 拓竹：一直连着 MQTT（TLS 8883），收打印机推送；每 5 分钟要一次全量（pushall），时间错开。
- Creality 原厂固件（WebSocket 9999）/ Klipper Moonraker（HTTP）：按状态错开轮询：
  打印中 / 暂停 5 秒一次，空闲 30 秒一次，连不上按 15 秒 → 30 → 60 … 最多 10 分钟退避（每台单独算，一台出错不影响别的）。
- 同时建立连接的数量有上限（MAX_CONNECTING），开机时几千台不会一起连。
- 状态变化（空闲 → 打印中 …）交给单独一个线程去通知生产模块（不卡住连接）。
- 线程数固定：事件循环 1 个 + 通知 1 个，和打印机台数无关。

运行方式：
  默认在 ERP 进程里跑（printers.start()）。
  打印机多了可以拆出去：ERP 设置环境变量 PRINTER_WORKER=external，另外运行 `python -m core.printer_worker`
  （同一个数据目录）。后台进程把状态写进数据库表 printer_state，ERP 从表里读；暂停 / 继续 / 取消 / 开始打印
  通过表 printer_cmds 交给后台进程执行。
  再多可以按分组分给几个后台进程：设置 printer_workers = {"w2": ["B 区", "C 区"]}，
  运行 `PRINTER_WORKER_ID=w2 python -m core.printer_worker`；没分配的分组归默认进程（id 为空）。
"""
import asyncio
import base64
import json
import os
import queue
import random
import ssl
import struct
import threading
import time
import traceback

FAST_S = 5            # 打印中 / 暂停：几秒读一次
SLOW_S = 30           # 空闲 / 打完
BACKOFF0 = 15         # 连不上：第一次等多久再试
BACKOFF_MAX = 600     # 最多等 10 分钟
PUSHALL_S = 300       # 拓竹：每 5 分钟要一次全量状态
KEEPALIVE = 30        # MQTT 心跳
MAX_CONNECTING = 64   # 同时建立连接的上限
RELOAD_S = 5          # 每几秒对一次设置（增删打印机、改 IP）


def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False          # 打印机用的是自签名证书
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


_SSL = None


async def default_open(host, port, tls, timeout):
    global _SSL
    if tls and _SSL is None:
        _SSL = _ssl_ctx()
    return await asyncio.wait_for(asyncio.open_connection(host, port, ssl=_SSL if tls else None), timeout)


# ---------------- MQTT 报文 ----------------
def _enc_str(s):
    b = s.encode("utf-8")
    return struct.pack("!H", len(b)) + b


def _enc_len(n):
    out = bytearray()
    while True:
        d = n % 128
        n //= 128
        if n:
            d |= 0x80
        out.append(d)
        if not n:
            return bytes(out)


def _pkt(header, body):
    return bytes([header]) + _enc_len(len(body)) + body


def mqtt_connect(client_id, user, password, keepalive=KEEPALIVE):
    flags = 0x02
    payload = _enc_str(client_id)
    if user:
        flags |= 0x80
        payload += _enc_str(user)
    if password:
        flags |= 0x40
        payload += _enc_str(password)
    return _pkt(0x10, _enc_str("MQTT") + bytes([4, flags]) + struct.pack("!H", keepalive) + payload)


def mqtt_publish(topic, payload):
    if isinstance(payload, (dict, list)):
        payload = json.dumps(payload)
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return _pkt(0x30, _enc_str(topic) + payload)


def mqtt_subscribe(pid, topic):
    return _pkt(0x82, struct.pack("!H", pid) + _enc_str(topic) + b"\x00")


async def mqtt_read(reader):
    h = (await reader.readexactly(1))[0]
    mult, length = 1, 0
    while True:
        d = (await reader.readexactly(1))[0]
        length += (d & 0x7F) * mult
        if not d & 0x80:
            break
        mult *= 128
    return h & 0xF0, (await reader.readexactly(length) if length else b"")


# ---------------- WebSocket / HTTP（不用第三方库） ----------------
async def ws_handshake(reader, writer, host, port, path="/"):
    key = base64.b64encode(os.urandom(16)).decode()
    writer.write((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    await writer.drain()
    head = await reader.readuntil(b"\r\n\r\n")
    if b" 101 " not in head.split(b"\r\n", 1)[0]:
        raise ConnectionError("WebSocket 握手失败")


def ws_frame(text, op=0x1):
    data = text.encode("utf-8") if isinstance(text, str) else text
    mask = os.urandom(4)
    n = len(data)
    if n < 126:
        head = bytes([0x80 | op, 0x80 | n])
    elif n < 65536:
        head = bytes([0x80 | op, 0x80 | 126]) + struct.pack("!H", n)
    else:
        head = bytes([0x80 | op, 0x80 | 127]) + struct.pack("!Q", n)
    return head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data))


async def ws_read(reader, writer):
    parts = []
    while True:
        b1, b2 = await reader.readexactly(2)
        op, fin = b1 & 0x0F, b1 & 0x80
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack("!H", await reader.readexactly(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", await reader.readexactly(8))[0]
        mask = await reader.readexactly(4) if b2 & 0x80 else None
        data = await reader.readexactly(n) if n else b""
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        if op == 0x8:
            raise ConnectionError("对方关闭了连接")
        if op == 0x9:
            writer.write(ws_frame(data, 0xA))
            continue
        if op in (0x0, 0x1, 0x2):
            parts.append(data)
            if fin:
                return b"".join(parts).decode("utf-8", "replace")


def _dechunk(body):
    out, i = b"", 0
    while i < len(body):
        j = body.find(b"\r\n", i)
        if j < 0:
            break
        n = int(body[i:j].split(b";")[0] or b"0", 16)
        if n == 0:
            break
        out += body[j + 2:j + 2 + n]
        i = j + 2 + n + 2
    return out


async def http_get_json(mgr, host, port, path, timeout=5):
    async with mgr.sem:
        reader, writer = await mgr.open(host, port, False, timeout)
    try:
        writer.write(f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\nAccept: application/json\r\n\r\n".encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(-1), timeout)
    finally:
        writer.close()
    head, _, body = data.partition(b"\r\n\r\n")
    first = head.split(b"\r\n", 1)[0]
    if b" 200" not in first:
        raise ConnectionError("HTTP " + first.decode("latin-1", "replace"))
    if b"transfer-encoding: chunked" in head.lower():
        body = _dechunk(body)
    return json.loads(body.decode("utf-8", "replace"))


# ---------------- 每台打印机一个「连接」（协程，不是线程） ----------------
class Link:
    kind = ""

    def __init__(self, mgr, pid, idx, conn):
        self.mgr, self.pid, self.idx, self.conn = mgr, pid, idx, dict(conn)
        self.key = Link.key_of(conn)
        self.task = None
        self.wake = asyncio.Event()
        self.closed = False
        self.fails = 0
        self.last = {}
        self.connected = False
        self.polls = 0

    @staticmethod
    def key_of(c):
        return (c.get("type"), c.get("detected"), (c.get("host") or "").strip(), (c.get("serial") or "").strip(),
                (c.get("access_code") or "").strip(), str(c.get("port") or ""))

    def backoff(self):
        d = min(BACKOFF_MAX, BACKOFF0 * (2 ** max(0, self.fails - 1)))
        return d * random.uniform(0.85, 1.15)

    async def nap(self, seconds):
        self.wake.clear()
        try:
            await asyncio.wait_for(self.wake.wait(), max(0.01, seconds))
        except asyncio.TimeoutError:
            pass

    def offline(self, e):
        from . import printers as pr
        self.fails += 1
        self.connected = False
        self.mgr.set(self, {"state": "offline", "error": pr._human_err(e), "conn": self.kind, "fails": self.fails})

    def stop(self):
        self.closed = True
        if self.task:
            self.task.cancel()


class BambuMQTT(Link):
    kind = "bambu"

    def __init__(self, *a):
        super().__init__(*a)
        self.raw = {}
        self.writer = None
        self.serial = (self.conn.get("serial") or "").strip()

    async def run(self):
        await asyncio.sleep(random.uniform(0, self.mgr.stagger))
        while not self.closed:
            writer = None
            try:
                async with self.mgr.sem:
                    reader, writer = await self.mgr.open(self.conn["host"].strip(), self.mgr.port("bambu", self.conn), self.mgr.tls, 8)
                    writer.write(mqtt_connect(f"lh-{os.getpid()}-{self.pid}", "bblp", (self.conn.get("access_code") or "").strip()))
                    await writer.drain()
                    ptype, body = await asyncio.wait_for(mqtt_read(reader), 8)
                if ptype != 0x20 or len(body) < 2:
                    raise ConnectionError("打印机没有正常回应（MQTT）")
                if body[1] != 0:
                    raise ConnectionError({4: "用户名或访问码不对", 5: "没有授权（访问码不对，或打印机没开局域网模式）"}.get(
                        body[1], f"连接被拒绝（代码 {body[1]}）"))
                self.writer = writer
                writer.write(mqtt_subscribe(1, f"device/{self.serial}/report"))
                await self.pushall()
                self.connected = True
                self.fails = 0
                last_ping = last_push = time.monotonic()
                push_every = PUSHALL_S * random.uniform(0.8, 1.2)
                while not self.closed:
                    now = time.monotonic()
                    wait = max(0.05, min(last_ping + KEEPALIVE / 2, last_push + push_every) - now)
                    try:
                        ptype, body = await asyncio.wait_for(mqtt_read(reader), wait)
                    except asyncio.TimeoutError:
                        now = time.monotonic()
                        if now - last_ping >= KEEPALIVE / 2:
                            writer.write(_pkt(0xC0, b""))
                            await writer.drain()
                            last_ping = now
                        if now - last_push >= push_every:
                            await self.pushall()
                            last_push = now
                        continue
                    if ptype == 0x30 and len(body) >= 2:
                        tl = struct.unpack("!H", body[:2])[0]
                        self._msg(body[2 + tl:])
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001  断线：这一台单独退避重连
                self.offline(e)
            finally:
                self.connected = False
                self.writer = None
                if writer:
                    try:
                        writer.close()
                    except Exception:  # noqa: BLE001
                        pass
            if not self.closed:
                await self.nap(self.backoff() if self.fails else 1)

    def _msg(self, payload):
        from . import printers as pr
        try:
            d = json.loads(payload)
        except ValueError:
            return
        p = d.get("print") if isinstance(d, dict) else None
        if not isinstance(p, dict):
            return
        for k, v in p.items():          # P1 系列只推送变化的部分，合并
            if k == "ams" and isinstance(v, dict) and isinstance(self.raw.get("ams"), dict):
                self.raw["ams"].update(v)
            else:
                self.raw[k] = v
        self.polls += 1
        self.mgr.set(self, pr.bambu_normalize(self.raw))

    async def publish(self, payload):
        if not self.writer or not self.connected:
            raise ConnectionError("打印机还没连上")
        self.writer.write(mqtt_publish(f"device/{self.serial}/request", payload))
        await self.writer.drain()

    async def pushall(self):
        w = self.writer
        if w:
            w.write(mqtt_publish(f"device/{self.serial}/request", {"pushing": {"sequence_id": "0", "command": "pushall"}}))
            await w.drain()


class Poller(Link):
    """Creality 原厂固件 / Moonraker：按状态错开轮询。"""

    async def run(self):
        await asyncio.sleep(random.uniform(0, self.mgr.stagger))
        while not self.closed:
            try:
                st = await asyncio.wait_for(self.poll(), 20)
                self.fails = 0
                self.connected = True
                self.polls += 1
                self.mgr.set(self, st)
                delay = self.mgr.fast if st.get("state") in ("printing", "paused") else self.mgr.slow
                delay *= random.uniform(0.9, 1.1)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.offline(e)
                delay = self.backoff()
            await self.nap(delay)


class CrealityWS(Poller):
    kind = "creality"

    async def poll(self):
        from . import printers as pr
        host = self.conn["host"].strip()
        port = self.mgr.port("creality", self.conn)
        async with self.mgr.sem:
            reader, writer = await self.mgr.open(host, port, False, 6)
            await asyncio.wait_for(ws_handshake(reader, writer, host, port), 6)
        data = {}
        try:
            end = time.monotonic() + self.mgr.creality_wait
            last = None
            while time.monotonic() < end:
                left = end - time.monotonic()
                if last and "state" in data:
                    left = min(left, 0.8)        # 已经拿到状态，再等一下有没有后续的
                try:
                    msg = await asyncio.wait_for(ws_read(reader, writer), max(0.05, left))
                except asyncio.TimeoutError:
                    if last and "state" in data:
                        break
                    continue
                last = time.monotonic()
                try:
                    m = json.loads(msg)
                except ValueError:
                    continue
                if isinstance(m, dict):
                    data.update(m)
        finally:
            try:
                writer.write(bytes([0x88, 0x80]) + b"\0\0\0\0")
                writer.close()
            except Exception:  # noqa: BLE001
                pass
        if not data:
            raise ConnectionError("Creality 打印机没有发来状态")
        return pr.creality_normalize(data)


class MoonrakerHTTP(Poller):
    kind = "moonraker"
    Q = "/printer/objects/query?print_stats&display_status&extruder&heater_bed&virtual_sdcard"

    def __init__(self, *a):
        super().__init__(*a)
        self.base_port = None

    async def poll(self):
        from . import printers as pr
        host = self.conn["host"].strip()
        if not self.base_port:
            ports = [int(self.conn["port"])] if str(self.conn.get("port") or "").isdigit() else self.mgr.port("moonraker", self.conn)
            for port in ports if isinstance(ports, list) else [ports]:
                try:
                    d = await http_get_json(self.mgr, host, port, "/server/info", 3)
                    if "result" in d:
                        self.base_port = port
                        break
                except Exception:  # noqa: BLE001
                    continue
            if not self.base_port:
                raise ConnectionError("Moonraker 没有回应")
        try:
            d = await http_get_json(self.mgr, host, self.base_port, self.Q, 5)
        except Exception:
            self.base_port = None
            raise
        return pr.moonraker_normalize(d["result"]["status"])


KINDS = {"bambu": BambuMQTT, "creality": CrealityWS, "moonraker": MoonrakerHTTP}


class Manager:
    def __init__(self, worker_id="", persist=False, opener=None, tls=True, ports=None, cfg_loader=None,
                 fast=FAST_S, slow=SLOW_S, stagger=None, creality_wait=2.5, reload_s=RELOAD_S):
        self.worker_id = worker_id or ""
        self.persist = persist              # 单独的后台进程：状态写进数据库，ERP 从表里读
        self.open = opener or default_open
        self.tls = tls
        self.ports = ports or {}
        self.cfg_loader = cfg_loader
        self.fast, self.slow = fast, slow
        self.stagger_fixed = stagger           # None = 按台数错开：几台马上连，1000 台分 20 秒连完
        self.stagger = 0.5 if stagger is None else stagger
        self.creality_wait = creality_wait
        self.reload_s = reload_s
        self.links = {}
        self.loop = None
        self.thread = None
        self.events = queue.Queue()
        self.dirty = {}
        self._dlock = threading.Lock()
        self.stopping = False
        self._kick = None
        self.sem = None
        self.sets = 0
        self.idmap, self.idxmap = {}, {}      # 稳定 id ↔ 序号（只在测试用自己的设置 cfg_loader 时用；平时读设置文件）
        self.cfg_key = None
        self.executed = 0                     # 执行过的 ERP 指令数（测试看有没有重复执行）
        self._pool = None

    # ---- 线程 ----
    def start(self):
        if self.thread:
            return self
        ready = threading.Event()
        self.thread = threading.Thread(target=self._thread_main, args=(ready,), daemon=True, name="printer-mgr")
        self.thread.start()
        threading.Thread(target=self._dispatch, daemon=True, name="printer-events").start()
        ready.wait(5)
        return self

    def stop(self):
        self.stopping = True
        if self.loop:
            self.loop.call_soon_threadsafe(self._cancel_all)

    def _cancel_all(self):
        for link in list(self.links.values()):
            link.stop()
        self.links.clear()
        if self._kick:
            self._kick.set()

    def _thread_main(self, ready):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.sem = asyncio.Semaphore(MAX_CONNECTING)
        self._kick = asyncio.Event()
        ready.set()
        try:
            self.loop.run_until_complete(self._main())
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    def _read_cfg(self):
        """读设置（在单独的线程里跑，不卡事件循环；load_config 按文件版本缓存，没改过很快）。"""
        from . import db
        try:
            return self.cfg_loader() if self.cfg_loader else _load_cfg()
        finally:
            try:
                db.release()
            except Exception:  # noqa: BLE001
                pass

    async def _main(self):
        from . import db
        from concurrent.futures import ThreadPoolExecutor
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="printer-cfg")
        while not self.stopping:
            try:
                cfg = await self.loop.run_in_executor(self._pool, self._read_cfg)
                self._sync(cfg)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            finally:
                try:
                    db.release()
                except Exception:  # noqa: BLE001
                    pass
            self._kick.clear()
            try:
                await asyncio.wait_for(self._kick.wait(), self.reload_s)
            except asyncio.TimeoutError:
                pass
        self._pool.shutdown(wait=False)

    def call(self, coro, timeout=15):
        """在别的线程（网页请求）里调连接上的协程，等结果。"""
        if not self.loop:
            raise ConnectionError("打印机连接服务没有运行")
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def kick(self, pid=None):
        """马上对一次设置；pid 给了就让这一台马上读一次。"""
        if not self.loop:
            return

        def go():
            if self._kick:
                self._kick.set()
            link = self.links.get(pid)
            if link:
                link.fails = 0
                link.wake.set()
        self.loop.call_soon_threadsafe(go)

    # ---- 哪些打印机归这个进程管 ----
    def mine(self, p, cfg):
        owner = {}
        for wid, groups in (cfg.get("printer_workers") or {}).items():
            for g in groups or []:
                owner[str(g)] = str(wid)
        return owner.get(str(p.get("group") or ""), "") == self.worker_id

    def port(self, kind, conn):
        if kind in self.ports:
            return self.ports[kind]
        if kind == "bambu":
            return 8883
        if kind == "creality":
            return 9999
        return [7125, 4408, 4409]

    def _sync(self, cfg):
        from . import printers as pr
        seen = set()
        idmap = {}
        for i, p in enumerate(cfg.get("printers") or []):
            idmap[p.get("id") or f"#{i}"] = i
        self.idmap, self.idxmap = idmap, {i: k for k, i in idmap.items()}
        if self.stagger_fixed is None:
            self.stagger = min(SLOW_S, max(0.5, len(cfg.get("printers") or []) / 50))
        for i, p in enumerate(cfg.get("printers") or []):
            pid = p.get("id") or f"#{i}"
            if not self.mine(p, cfg):
                continue
            c = pr.conn_cfg(p)
            t = pr._type(c)
            seen.add(pid)
            link = self.links.get(pid)
            if t not in KINDS or not (c.get("host") or "").strip():
                if link:
                    link.stop()
                    self.links.pop(pid, None)
                if t == "none" and ((pr._status.get(pid) or {}).get("state") != "none"):
                    self._store(pid, {"state": "none", "conn": "none"})
                continue
            if link and link.key == Link.key_of(c) and link.kind == t:
                link.idx = i                   # 只是显示用：状态和通知都按稳定 id，通知时才换成现在的序号
                continue
            if link:
                link.stop()
            link = KINDS[t](self, pid, i, c)
            self.links[pid] = link
            link.task = self.loop.create_task(link.run())
        for pid in [k for k in self.links if k not in seen]:
            self.links.pop(pid).stop()

    # ---- 状态 ----
    def set(self, link, st):
        if link.closed:
            return
        st = dict(st)
        link.last = st
        self.sets += 1
        self._store(link.pid, st)

    def _store(self, pid, st):
        """v2.54 复审：按稳定 id 记状态、排队通知（以前按 link.idx：删了打印机后、下一次对设置前（最多 5 秒；
        后台进程模式根本不知道）收到的状态会记到别的打印机上，生产模块可能把别的打印机的那一盘记成打完）。"""
        from . import printers as pr
        old, changed = pr._store(pid, st)
        if changed:
            self.events.put((pid, old, st))
        if self.persist:
            with self._dlock:
                self.dirty[pid] = st

    def _dispatch(self):
        """单独一个线程：状态变化通知生产模块；后台进程模式下把状态写进数据库、执行 ERP 发来的指令。"""
        from . import db
        from . import printers as pr
        last_flush = 0
        while not self.stopping:
            try:
                ev = self.events.get(timeout=0.5)
            except queue.Empty:
                ev = None
            try:
                if ev:
                    pr.fire_pid(*ev)        # 通知时才把 id 换成现在的序号（设置文件改了马上认出来）
                if self.persist and time.time() - last_flush >= 1:
                    last_flush = time.time()
                    self.flush()
                    self.run_commands()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            finally:
                try:
                    db.release()
                except Exception:  # noqa: BLE001
                    pass

    def flush(self):
        with self._dlock:
            dirty, self.dirty = self.dirty, {}
        if not dirty:
            return 0
        from . import db
        c = db.conn()
        ensure_tables(c)
        from . import printers as pr
        now = time.time()
        c.executemany("INSERT INTO printer_state(pid, idx, data, updated, worker) VALUES(?,?,?,?,?) ON CONFLICT(pid) DO UPDATE SET "
                      "idx=excluded.idx, data=excluded.data, updated=excluded.updated, worker=excluded.worker",
                      [(pid, pr.index_of(pid), json.dumps(st, ensure_ascii=False), now, self.worker_id) for pid, st in dirty.items()])
        c.commit()
        return len(dirty)

    def run_commands(self):
        """ERP（PRINTER_WORKER=external）发来的指令：只执行归这个进程管的打印机。
        v2.54 复审：先原子地「认领」（new → running，带上进程 id），认领不到（别的进程认领了 / ERP 已经放弃）就跳过；
        同一个幂等键（同一次发送）已经在执行 / 执行过了 → 不再执行（标成 dup）。"""
        from . import db
        c = db.conn()
        ensure_tables(c)
        rows = c.execute("SELECT * FROM printer_cmds WHERE status='new' AND created > ? ORDER BY id", (time.time() - 60,)).fetchall()
        me = f"{self.worker_id or '-'}@{os.getpid()}"
        for r in rows:
            link = self.links.get(r["pid"])
            if not link:
                continue
            key = r["ikey"] or ""
            n = c.execute("UPDATE printer_cmds SET status='running', worker=? WHERE id=? AND status='new' AND (?='' OR NOT EXISTS("
                          "SELECT 1 FROM printer_cmds x WHERE x.ikey=? AND x.id<>printer_cmds.id AND x.status IN ('running','done')))",
                          (me, r["id"], key, key)).rowcount
            c.commit()
            if not n:
                if key:
                    n = c.execute("UPDATE printer_cmds SET status='dup', worker=?, result=?, done=? WHERE id=? AND status='new'",
                                  (me, "同一次发送已经执行过，不重复执行", time.time(), r["id"])).rowcount
                    c.commit()
                continue
            try:
                payload = json.loads(r["payload"] or "{}")
                if r["op"] == "kick":
                    self.kick(r["pid"])
                elif r["op"] == "publish":
                    self.executed += 1
                    self.call(link.publish(payload), 10)
                else:
                    raise ValueError("不支持的指令")
                res, status = "", "done"
            except Exception as e:  # noqa: BLE001
                res, status = str(e) or type(e).__name__, "error"
            c.execute("UPDATE printer_cmds SET status=?, result=?, done=? WHERE id=?", (status, res, time.time(), r["id"]))
            c.commit()

    def stats(self):
        return {"links": len(self.links), "connected": sum(1 for x in self.links.values() if x.connected),
                "sets": self.sets, "threads": threading.active_count(), "worker": self.worker_id}


def _load_cfg():
    from .config import load_config
    return load_config()


_TABLES_OK = set()


def ensure_tables(c):
    from . import db
    if db.DB_PATH in _TABLES_OK:
        return
    c.execute("CREATE TABLE IF NOT EXISTS printer_state(pid TEXT PRIMARY KEY, idx INTEGER, data TEXT, updated REAL, worker TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS printer_cmds(id INTEGER PRIMARY KEY AUTOINCREMENT, pid TEXT, op TEXT, payload TEXT, "
              "status TEXT DEFAULT 'new', result TEXT, created REAL, done REAL, worker TEXT, ikey TEXT DEFAULT '')")
    cols = {r[1] for r in c.execute("PRAGMA table_info(printer_cmds)")}
    for col, typ in (("worker", "TEXT"), ("ikey", "TEXT DEFAULT ''")):    # v2.54 复审：认领的进程、幂等键
        if col not in cols:
            try:
                c.execute(f"ALTER TABLE printer_cmds ADD COLUMN {col} {typ}")
            except Exception:  # noqa: BLE001  别的进程刚加过
                pass
    c.execute("CREATE INDEX IF NOT EXISTS printer_cmds_ikey ON printer_cmds(ikey)")
    c.commit()
    _TABLES_OK.add(db.DB_PATH)
