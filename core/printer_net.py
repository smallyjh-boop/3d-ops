"""和打印机通信用的几个小工具（不依赖第三方库，Windows / NAS 都能直接用）：

- MiniMQTT：MQTT 3.1.1 客户端（TLS），用于拓竹 Bambu Lab 局域网模式（端口 8883）。
- ws_*：最简单的 WebSocket 客户端，用于 Creality K1 系列原厂固件（端口 9999）。
- ImplicitFTPS：隐式 TLS 的 FTP，用于把文件传到拓竹打印机（端口 990）。
"""
import base64
import ftplib
import json
import os
import socket
import ssl
import struct
import threading
import time


def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False          # 打印机用的是自签名证书
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# ---------------- MQTT ----------------
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


class MiniMQTT:
    """够用就好：连接、订阅、发布（QoS 0）、心跳、收消息回调。"""

    def __init__(self, host, port=8883, username="", password="", client_id=None, use_tls=True, keepalive=30):
        self.host, self.port, self.username, self.password = host, port, username, password
        self.client_id = client_id or f"lh-{os.getpid()}-{int(time.time() * 1000) % 100000}"
        self.use_tls, self.keepalive = use_tls, keepalive
        self.sock = None
        self.on_message = None
        self._lock = threading.Lock()
        self._pid = 1
        self.connected = False

    def connect(self, timeout=8):
        raw = socket.create_connection((self.host, self.port), timeout=timeout)
        self.sock = _ssl_ctx().wrap_socket(raw, server_hostname=self.host) if self.use_tls else raw
        flags = 0x02
        payload = _enc_str(self.client_id)
        if self.username:
            flags |= 0x80
            payload += _enc_str(self.username)
        if self.password:
            flags |= 0x40
            payload += _enc_str(self.password)
        var = _enc_str("MQTT") + bytes([4, flags]) + struct.pack("!H", self.keepalive)
        self._send(0x10, var + payload)
        ptype, body = self._read_packet()
        if ptype != 0x20 or len(body) < 2:
            raise ConnectionError("打印机没有正常回应（MQTT）")
        if body[1] != 0:
            codes = {4: "用户名或访问码不对", 5: "没有授权（访问码不对，或打印机没开局域网模式）"}
            raise ConnectionError(codes.get(body[1], f"连接被拒绝（代码 {body[1]}）"))
        self.connected = True

    def _send(self, header, body):
        with self._lock:
            self.sock.sendall(bytes([header]) + _enc_len(len(body)) + body)

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("连接断开")
            buf += chunk
        return buf

    def _read_packet(self):
        h = self._recv_exact(1)[0]
        mult, length = 1, 0
        while True:
            d = self._recv_exact(1)[0]
            length += (d & 0x7F) * mult
            if not d & 0x80:
                break
            mult *= 128
        return h & 0xF0, (self._recv_exact(length) if length else b"")

    def subscribe(self, topic):
        self._pid = self._pid % 65000 + 1
        self._send(0x82, struct.pack("!H", self._pid) + _enc_str(topic) + b"\x00")

    def publish(self, topic, payload):
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        self._send(0x30, _enc_str(topic) + payload)

    def ping(self):
        self._send(0xC0, b"")

    def loop(self, stop_event=None):
        """阻塞读取消息，直到断开或 stop_event 被设置。"""
        self.sock.settimeout(1.0)
        last_ping = time.time()
        while not (stop_event and stop_event.is_set()):
            if time.time() - last_ping > self.keepalive / 2:
                self.ping()
                last_ping = time.time()
            try:
                ptype, body = self._read_packet()
            except (socket.timeout, ssl.SSLError) as e:
                if isinstance(e, ssl.SSLError) and "timed out" not in str(e):
                    raise
                continue
            if ptype == 0x30 and len(body) >= 2:
                tl = struct.unpack("!H", body[:2])[0]
                topic = body[2:2 + tl].decode("utf-8", "replace")
                msg = body[2 + tl:]
                if self.on_message:
                    try:
                        self.on_message(topic, msg)
                    except Exception:   # 回调出错不影响连接
                        pass

    def close(self):
        self.connected = False
        try:
            self._send(0xE0, b"")
        except Exception:  # 已断开
            pass
        try:
            self.sock.close()
        except Exception:  # 已断开
            pass


# ---------------- WebSocket ----------------
class _WS:
    """socket 外面包一层，带上读缓冲。"""

    def __init__(self, sock):
        self.sock = sock
        self._ws_buf = b""

    def __getattr__(self, name):
        return getattr(self.sock, name)


def ws_connect(host, port, path="/", timeout=6):
    s = _WS(socket.create_connection((host, port), timeout=timeout))
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
    s.sendall(req.encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = s.recv(1024)
        if not chunk:
            raise ConnectionError("WebSocket 握手失败")
        resp += chunk
    if b" 101 " not in resp.split(b"\r\n", 1)[0]:
        raise ConnectionError("WebSocket 握手失败：" + resp.split(b"\r\n", 1)[0].decode("latin-1"))
    s._ws_buf = resp.split(b"\r\n\r\n", 1)[1]
    return s


def ws_send(s, text):
    data = text.encode("utf-8") if isinstance(text, str) else text
    mask = os.urandom(4)
    n = len(data)
    if n < 126:
        head = bytes([0x81, 0x80 | n])
    elif n < 65536:
        head = bytes([0x81, 0x80 | 126]) + struct.pack("!H", n)
    else:
        head = bytes([0x81, 0x80 | 127]) + struct.pack("!Q", n)
    s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


def _ws_read(s, n):
    buf = s._ws_buf
    while len(buf) < n:
        chunk = s.recv(65536)
        if not chunk:
            raise ConnectionError("连接断开")
        buf += chunk
    s._ws_buf = buf[n:]
    return buf[:n]


def ws_recv(s):
    """读一条文本消息（自动回应 ping，拼接分片）。"""
    parts = []
    while True:
        b1, b2 = _ws_read(s, 2)
        op, fin = b1 & 0x0F, b1 & 0x80
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack("!H", _ws_read(s, 2))[0]
        elif n == 127:
            n = struct.unpack("!Q", _ws_read(s, 8))[0]
        mask = _ws_read(s, 4) if b2 & 0x80 else None
        data = _ws_read(s, n)
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        if op == 0x8:
            raise ConnectionError("对方关闭了连接")
        if op == 0x9:      # ping → pong
            s.sendall(bytes([0x8A, 0x80 | len(data)]) + b"\0\0\0\0" + data)
            continue
        if op in (0x1, 0x2, 0x0):
            parts.append(data)
            if fin:
                return b"".join(parts).decode("utf-8", "replace")


def ws_close(s):
    try:
        s.sendall(bytes([0x88, 0x80]) + b"\0\0\0\0")
    except OSError:
        pass
    try:
        s.close()
    except OSError:
        pass


# ---------------- 隐式 FTPS（拓竹）----------------
class ImplicitFTPS(ftplib.FTP_TLS):
    """拓竹打印机的 FTP：端口 990，连接一开始就是 TLS，数据通道要复用 TLS 会话。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, context=_ssl_ctx(), **kw)
        self._sock = None

    @property
    def sock(self):
        return self._sock

    @sock.setter
    def sock(self, value):
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value, server_hostname=self.host)
        self._sock = value

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn, server_hostname=self.host, session=self.sock.session)
        return conn, size


def bambu_upload(host, access_code, local_path, remote_name, timeout=60):
    ftp = ImplicitFTPS(timeout=timeout)
    ftp.connect(host, 990)
    ftp.login("bblp", access_code)
    ftp.prot_p()
    with open(local_path, "rb") as f:
        ftp.storbinary(f"STOR /{remote_name}", f)
    try:
        ftp.quit()
    except Exception:  # 有的固件不回应 QUIT
        ftp.close()


def port_open(host, port, timeout=1.5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
