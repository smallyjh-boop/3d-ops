"""局域网里找打印机（v2.54，只有老板能用）：

1. 拓竹广播（SSDP）：拓竹打印机每隔几秒往 UDP 2021 广播自己的 IP、序列号、机型代码、局域网模式；
   也会回应发到 1990 / 239.255.255.250 的 M-SEARCH。听几秒就能拿到序列号（不用去屏幕上抄）。
2. 扫端口：服务器所在的网段（只扫 /22 以内，最多 1024 个地址）逐个试 8883（拓竹）/ 9999（Creality 原厂）/
   7125、4408（Klipper Moonraker），每个端口很短的超时，同时最多 SCAN_CONCURRENCY 个连接。
找到的设备按 IP 合并，猜机型，标出已经在系统里的。
"""
import asyncio
import ipaddress
import re
import socket
import time

SCAN_PORTS = [(8883, "bambu"), (9999, "creality"), (7125, "moonraker"), (4408, "moonraker")]
SCAN_CONCURRENCY = 128
SCAN_TIMEOUT = 0.4
MAX_HOSTS = 1024
SSDP_PORTS = (2021, 1990)
# 拓竹广播里的机型代码 → 机型
BAMBU_DEV = {"3DPrinter-X1-Carbon": "Bambu Lab X1 Carbon", "BL-P001": "Bambu Lab X1 Carbon", "3DPrinter-X1": "Bambu Lab X1 Carbon",
             "BL-P002": "Bambu Lab X1 Carbon", "C13": "Bambu Lab X1E", "C11": "Bambu Lab P1P", "C12": "Bambu Lab P1S",
             "N1": "Bambu Lab A1 mini", "N2S": "Bambu Lab A1", "O1D": "Bambu Lab H2D", "O1S": "Bambu Lab H2S",
             "N7": "Bambu Lab P2S"}
SERIAL_PREFIX = {"00M": "Bambu Lab X1 Carbon", "03W": "Bambu Lab X1E", "01S": "Bambu Lab P1P", "01P": "Bambu Lab P1S",
                 "030": "Bambu Lab A1 mini", "039": "Bambu Lab A1", "094": "Bambu Lab H2D"}


def parse_ssdp(text, src_ip=""):
    """一条拓竹 SSDP 广播 → {ip, serial, model, model_code, name, lan_mode}；不是拓竹的返回 None。"""
    h = {}
    for line in str(text or "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            h[k.strip().lower()] = v.strip()
    usn = h.get("usn", "")
    if "bambu" not in str(text).lower() and not h.get("devmodel.bambu.com"):
        return None
    serial = re.sub(r"[^A-Za-z0-9]", "", usn.split("::")[0].replace("uuid:", ""))[:20].upper()
    code = h.get("devmodel.bambu.com", "")
    model = BAMBU_DEV.get(code) or SERIAL_PREFIX.get(serial[:3]) or ""
    loc = h.get("location", "") or src_ip
    ip = re.sub(r"^https?://", "", loc).split(":")[0].split("/")[0] or src_ip
    conn = h.get("devconnect.bambu.com", "").lower()
    return {"ip": ip, "serial": serial, "model": model, "model_code": code, "name": h.get("devname.bambu.com", ""),
            "vendor": "bambu", "lan_mode": True if conn == "lan" else (False if conn == "cloud" else None),
            "source": "ssdp"}


MSEARCH = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1990\r\nMAN: \"ssdp:discover\"\r\nMX: 1\r\n"
           "ST: urn:bambulab-com:device:3dprinter:1\r\n\r\n").encode()


def listen_ssdp(seconds=3.0, ports=SSDP_PORTS, sock_factory=None):
    """听几秒拓竹广播（同时发一次 M-SEARCH）。端口被占用 / 没有权限就跳过。返回 {ip: 设备}。"""
    found = {}
    socks = []
    for port in ports:
        try:
            s = sock_factory(port) if sock_factory else socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            if not sock_factory:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.bind(("", port))
            s.settimeout(0.2)
            socks.append(s)
        except OSError:
            continue
    try:
        for s in socks:
            try:
                s.sendto(MSEARCH, ("239.255.255.250", 1990))
                s.sendto(MSEARCH, ("255.255.255.255", 1990))
            except OSError:
                pass
        end = time.time() + seconds
        while time.time() < end and socks:
            for s in socks:
                try:
                    data, addr = s.recvfrom(4096)
                except (socket.timeout, OSError):
                    continue
                d = parse_ssdp(data.decode("utf-8", "replace"), addr[0])
                if d and d["ip"]:
                    found[d["ip"]] = d
    finally:
        for s in socks:
            try:
                s.close()
            except OSError:
                pass
    return found


def local_subnets(env=None):
    """服务器自己的网段（不含 127.x、169.254.x、Docker 网桥 172.17）。只取 /22 以内，大的网段缩成服务器所在的 /24。"""
    from . import netdiag
    env = env or netdiag.default_env()
    out = []
    try:
        info = netdiag.collect_net("127.0.0.1", env)
    except Exception:  # noqa: BLE001
        info = {}
    for i in info.get("ifaces") or []:
        for a in i.get("addrs") or []:
            try:
                n = ipaddress.ip_interface(a)
            except ValueError:
                continue
            if n.ip.version != 4 or n.ip.is_loopback or n.ip.is_link_local or str(n.ip).startswith("172.17."):
                continue
            net = n.network if n.network.prefixlen >= 22 else ipaddress.ip_interface(f"{n.ip}/24").network
            if net not in out:
                out.append(net)
    if not out and env.get("fallback", True):     # 没有 ip 命令（Windows / Mac）：用默认出口的 IP，按 /24
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("192.0.2.1", 9))
            ip = s.getsockname()[0]
            s.close()
            if not ip.startswith(("127.", "0.")):
                out.append(ipaddress.ip_interface(f"{ip}/24").network)
        except OSError:
            pass
    return out


def hosts_of(subnets, limit=MAX_HOSTS):
    out = []
    for net in subnets:
        for h in net.hosts():
            out.append(str(h))
            if len(out) >= limit:
                return out
    return out


async def _probe(host, port, timeout, sem, connect):
    async with sem:
        try:
            if connect:
                ok = await connect(host, port, timeout)
            else:
                _r, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
                w.close()
                ok = True
        except (OSError, asyncio.TimeoutError):
            ok = False
        return host, port, ok


async def _scan(hosts, ports, timeout, concurrency, connect):
    sem = asyncio.Semaphore(concurrency)
    tasks = [_probe(h, p, timeout, sem, connect) for h in hosts for p, _k in ports]
    return await asyncio.gather(*tasks)


def scan(hosts, ports=SCAN_PORTS, timeout=SCAN_TIMEOUT, concurrency=SCAN_CONCURRENCY, connect=None):
    """扫端口。connect(host, port, timeout) 是协程（测试用假的），返回 True / False。返回 {ip: 设备}。"""
    res = asyncio.run(_scan(hosts, ports, timeout, concurrency, connect))
    kind = dict(ports)
    found = {}
    for host, port, ok in res:
        if not ok:
            continue
        d = found.setdefault(host, {"ip": host, "serial": "", "model": "", "vendor": "", "ports": [], "source": "scan"})
        d["ports"].append(port)
    for d in found.values():
        ks = [kind[p] for p in d["ports"]]
        d["vendor"] = "bambu" if "bambu" in ks else ("moonraker" if "moonraker" in ks else "creality")
        if d["vendor"] == "creality":
            d["model"] = "Creality K1C"        # 原厂固件分不出 K1 / K1C / K1 Max，先按 K1C，添加时可以改
        d["guess"] = True
    return found


def discover(cfg, seconds=3.0, scan_hosts=None, connect=None, ssdp=None, env=None):
    """拓竹广播 + 扫端口，按 IP 合并，标出已经在系统里的（按 IP / 序列号）。"""
    found = dict(ssdp if ssdp is not None else listen_ssdp(seconds))
    hosts = scan_hosts if scan_hosts is not None else hosts_of(local_subnets(env))
    t0 = time.time()
    for ip, d in scan(hosts, connect=connect).items():
        if ip in found:
            found[ip].setdefault("ports", d["ports"])
        else:
            found[ip] = d
    have_ip = {}
    have_sn = {}
    for p in cfg.get("printers") or []:
        c = p.get("conn") or {}
        if c.get("host"):
            have_ip[c["host"].strip()] = p.get("code")
        if c.get("serial"):
            have_sn[c["serial"].strip().upper()] = p.get("code")
    out = []
    for ip, d in found.items():
        d["exists"] = have_sn.get(d.get("serial") or "") or have_ip.get(ip) or ""
        out.append(d)

    def ipkey(d):
        try:
            return (0, int(ipaddress.IPv4Address(d["ip"])))
        except ValueError:
            return (1, 0)
    out.sort(key=ipkey)
    return {"devices": out, "scanned": len(hosts), "seconds": round(time.time() - t0, 1)}
