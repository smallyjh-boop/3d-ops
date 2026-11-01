"""测试用的假打印机（v2.54）：一个进程里同时开 拓竹 MQTT、Creality WebSocket、Moonraker HTTP 三种假服务，
可以接上千个连接（测连接管理能不能撑住几千台）。不是 t_ 开头，测试运行器不会单独跑它。

    python fake_printers.py <端口文件>     开好后把 {"mqtt": 端口, "ws": 端口, "http": 端口} 写进端口文件

拓竹：序列号最后一位是双数 → 打印中（每秒推一次进度），单数 → 空闲；访问码 badcode → 拒绝登录。
GET /stats（HTTP 端口）→ 当前连接数、收到的指令。
"""
import asyncio
import json
import os
import struct
import sys

STATS = {"mqtt_conns": 0, "mqtt_total": 0, "ws_total": 0, "http_total": 0, "commands": {}}


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


def _pkt(h, body):
    return bytes([h]) + _enc_len(len(body)) + body


async def _read(reader):
    h = (await reader.readexactly(1))[0]
    mult, length = 1, 0
    while True:
        d = (await reader.readexactly(1))[0]
        length += (d & 0x7F) * mult
        if not d & 0x80:
            break
        mult *= 128
    return h & 0xF0, (await reader.readexactly(length) if length else b"")


def _str_at(b, i):
    n = struct.unpack("!H", b[i:i + 2])[0]
    return b[i + 2:i + 2 + n].decode("utf-8", "replace"), i + 2 + n


def _report(serial, pct):
    printing = serial[-1:].isdigit() and int(serial[-1]) % 2 == 0
    d = {"print": {"gcode_state": "RUNNING" if printing else "IDLE", "mc_percent": pct if printing else 0,
                   "subtask_name": f"job-{serial}", "nozzle_temper": 220 if printing else 25, "bed_temper": 60}}
    topic = f"device/{serial}/report".encode()
    return _pkt(0x30, struct.pack("!H", len(topic)) + topic + json.dumps(d).encode())


async def mqtt_conn(reader, writer):
    STATS["mqtt_total"] += 1
    STATS["mqtt_conns"] += 1
    serial = None
    pct = 0
    try:
        ptype, body = await _read(reader)
        if ptype != 0x10:
            return
        flags = body[7]
        i = 10
        _cid, i = _str_at(body, i)
        pw = ""
        if flags & 0x80:
            _u, i = _str_at(body, i)
        if flags & 0x40:
            pw, i = _str_at(body, i)
        if pw == "badcode":
            writer.write(_pkt(0x20, b"\x00\x05"))
            await writer.drain()
            return
        writer.write(_pkt(0x20, b"\x00\x00"))
        await writer.drain()
        while True:
            try:
                ptype, body = await asyncio.wait_for(_read(reader), 1.0)
            except asyncio.TimeoutError:
                if serial and serial[-1:].isdigit() and int(serial[-1]) % 2 == 0:
                    pct = min(99, pct + 1)
                    writer.write(_report(serial, pct))
                    await writer.drain()
                continue
            if ptype == 0x80:                       # SUBSCRIBE
                pid = body[:2]
                topic, _ = _str_at(body, 2)
                serial = topic.split("/")[1]
                writer.write(_pkt(0x90, pid + b"\x00"))
            elif ptype == 0x30:                     # PUBLISH（请求）
                tl = struct.unpack("!H", body[:2])[0]
                msg = json.loads(body[2 + tl:])
                if (msg.get("pushing") or {}).get("command") == "pushall":
                    pct = pct or 10
                    writer.write(_report(serial, pct))
                elif "print" in msg:
                    STATS["commands"].setdefault(serial, []).append(msg["print"].get("command"))
            elif ptype == 0xC0:                     # PINGREQ
                writer.write(_pkt(0xD0, b""))
            elif ptype == 0xE0:
                return
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError, OSError):
        pass
    finally:
        STATS["mqtt_conns"] -= 1
        writer.close()


async def ws_conn(reader, writer):
    STATS["ws_total"] += 1
    try:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
        for m in ({"state": 1, "printProgress": 42, "printFileName": "a.gcode", "nozzleTemp": 210},
                  {"bedTemp0": 55, "err": {"errcode": 0, "key": 0, "value": ""}}):
            data = json.dumps(m).encode()
            writer.write(bytes([0x81, len(data)]) if len(data) < 126 else bytes([0x81, 126]) + struct.pack("!H", len(data)))
            writer.write(data)
        await writer.drain()
        await reader.read(10)        # 等客户端关
    except (asyncio.IncompleteReadError, ConnectionError, OSError, asyncio.LimitOverrunError):
        pass
    finally:
        writer.close()


async def http_conn(reader, writer):
    STATS["http_total"] += 1
    try:
        head = await reader.readuntil(b"\r\n\r\n")
        path = head.split(b" ")[1].decode()
        if path.startswith("/server/info"):
            body = {"result": {"klippy_state": "ready"}}
        elif path.startswith("/printer/objects/query"):
            body = {"result": {"status": {"print_stats": {"state": "printing", "filename": "m.gcode", "print_duration": 120},
                                          "display_status": {"progress": 0.5}, "extruder": {"temperature": 215},
                                          "heater_bed": {"temperature": 60}}}}
        elif path.startswith("/stats"):
            body = STATS
        else:
            writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
            return
        data = json.dumps(body).encode()
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + str(len(data)).encode() + b"\r\n\r\n" + data)
        await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError, OSError, asyncio.LimitOverrunError):
        pass
    finally:
        writer.close()


async def main(port_file, cert=None, key=None):
    m = await asyncio.start_server(mqtt_conn, "127.0.0.1", 0, backlog=2048)
    w = await asyncio.start_server(ws_conn, "127.0.0.1", 0, backlog=2048)
    h = await asyncio.start_server(http_conn, "127.0.0.1", 0, backlog=2048)
    ports = {"mqtt": m.sockets[0].getsockname()[1], "ws": w.sockets[0].getsockname()[1], "http": h.sockets[0].getsockname()[1]}
    if cert:                                   # 和真的拓竹一样走 TLS（自签名证书）
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        t = await asyncio.start_server(mqtt_conn, "127.0.0.1", 0, ssl=ctx, backlog=512)
        ports["mqtts"] = t.sockets[0].getsockname()[1]
    with open(port_file + ".tmp", "w") as f:
        json.dump(ports, f)
    os.replace(port_file + ".tmp", port_file)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:4]))
