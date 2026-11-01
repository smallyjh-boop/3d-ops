"""v2.53.0：打印机「网络诊断」。
1) 逐个端口试连并分类（通 / 拒绝 / 超时 / 找不到主机 / 其他）；
2) 读服务器网卡、路由、ARP（Linux 尽力而为，不需要 root；Windows / Mac 自动降级）；
3) 给出看得懂的结论和处理步骤（每条同时有中文 zh 和泰文 th）。
所有系统调用都可以通过 env 参数替换，方便测试。
"""
import errno
import ipaddress
import os
import re
import socket
import subprocess

BAMBU_PORTS = [(8883, "MQTT"), (990, "FTPS")]
MOONRAKER_PORTS = [(7125, "Moonraker"), (4408, "Fluidd/Mainsail"), (4409, "Moonraker")]
CREALITY_PORTS = [(9999, "Creality")]
WEB_PORTS = [(80, "HTTP")]

NOROUTE_ERRNOS = {errno.EHOSTUNREACH, errno.ENETUNREACH, getattr(errno, "EHOSTDOWN", -1), 10065, 10051}
REFUSED_ERRNOS = {errno.ECONNREFUSED, 10061}


def ports_for(ctype):
    """按连接方式决定要测哪些端口；自动 / 未设置就全测。"""
    if ctype == "bambu":
        p = BAMBU_PORTS
    elif ctype == "moonraker":
        p = MOONRAKER_PORTS
    elif ctype == "creality":
        p = CREALITY_PORTS + MOONRAKER_PORTS
    else:
        p = BAMBU_PORTS + MOONRAKER_PORTS + CREALITY_PORTS
    return list(p) + WEB_PORTS


def classify_exc(e):
    """异常 → (kind, errno)。kind：refused / timeout / noroute / other"""
    no = getattr(e, "errno", None)
    low = str(e).lower()
    if isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in low:
        return "timeout", no
    if no in REFUSED_ERRNOS or "refused" in low:
        return "refused", no
    if no in NOROUTE_ERRNOS or "no route" in low or "unreachable" in low or "host is down" in low:
        return "noroute", no
    return "other", no


def probe_port(host, port, timeout=2.0, connect=None):
    connect = connect or socket.create_connection
    try:
        s = connect((host, port), timeout=timeout)
        try:
            s.close()
        except Exception:
            pass
        return {"port": port, "kind": "ok", "errno": None, "msg": ""}
    except Exception as e:
        kind, no = classify_exc(e)
        return {"port": port, "kind": kind, "errno": no, "msg": str(e)}


def probe_all(host, ctype="auto", timeout=2.0, connect=None):
    from concurrent.futures import ThreadPoolExecutor
    pl = ports_for(ctype)
    with ThreadPoolExecutor(max_workers=len(pl)) as ex:
        res = list(ex.map(lambda pn: probe_port(host, pn[0], timeout, connect), pl))
    for r, (_, name) in zip(res, pl):
        r["name"] = name
    return res


def summarize_ports(ports):
    """端口结果 → 整体判断：open / refused / timeout / noroute / other"""
    kinds = [p["kind"] for p in ports]
    if "ok" in kinds:
        return "open"
    for k in ("noroute", "timeout", "other"):
        if k in kinds:
            return k
    return "refused" if kinds else "other"


# ---------------- 系统信息 ----------------
def _default_run(cmd, timeout=3):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def _default_read(path):
    try:
        with open(path, "r", errors="replace") as f:
            return f.read()
    except Exception:
        return None


def _default_listdir(path):
    try:
        return sorted(os.listdir(path))
    except Exception:
        return []


def default_env():
    return {"run": _default_run, "read": _default_read, "listdir": _default_listdir}


def parse_addr(text):
    """`ip -4 -o addr` → [{name, cidr, ip}]"""
    out = []
    for ln in (text or "").splitlines():
        m = re.match(r"\d+:\s+(\S+?)(?:@\S+)?\s+inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", ln)
        if m:
            out.append({"name": m.group(1), "ip": m.group(2), "cidr": f"{m.group(2)}/{m.group(3)}"})
    return out


def parse_routes(text):
    """`ip route` → [{dest, dev, src, linkdown, raw}]，保持原顺序（先出现的先用）。"""
    out = []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        dest = ln.split()[0]
        dev = re.search(r"\bdev\s+(\S+)", ln)
        src = re.search(r"\bsrc\s+(\S+)", ln)
        out.append({"dest": dest, "dev": dev.group(1) if dev else "", "src": src.group(1) if src else "",
                    "linkdown": "linkdown" in ln.split(), "raw": ln})
    return out


def parse_proc_route(text):
    """/proc/net/route（十六进制小端）→ 同 parse_routes 格式"""
    out = []
    for ln in (text or "").splitlines()[1:]:
        f = ln.split()
        if len(f) < 8:
            continue
        try:
            dest = socket.inet_ntoa(bytes.fromhex(f[1])[::-1])
            mask = socket.inet_ntoa(bytes.fromhex(f[7])[::-1])
            plen = bin(int(ipaddress.IPv4Address(mask))).count("1")
        except Exception:
            continue
        out.append({"dest": "default" if plen == 0 else f"{dest}/{plen}", "dev": f[0], "src": "", "linkdown": False, "raw": ln})
    return out


def parse_route_get(text):
    """`ip route get X` → {dev, src, via, linkdown}"""
    t = (text or "").strip().splitlines()
    if not t:
        return None
    ln = t[0]
    dev = re.search(r"\bdev\s+(\S+)", ln)
    if not dev:
        return None
    src = re.search(r"\bsrc\s+(\S+)", ln)
    via = re.search(r"\bvia\s+(\S+)", ln)
    return {"dev": dev.group(1), "src": src.group(1) if src else "", "via": via.group(1) if via else "",
            "linkdown": "linkdown" in ln.split()}


def parse_neigh(text):
    """`ip neigh show X` → {dev, state, mac}"""
    for ln in (text or "").splitlines():
        f = ln.split()
        if len(f) >= 3 and "dev" in f:
            dev = f[f.index("dev") + 1]
            mac = f[f.index("lladdr") + 1] if "lladdr" in f else ""
            return {"dev": dev, "state": f[-1], "mac": mac}
    return None


def parse_proc_arp(text, ip):
    for ln in (text or "").splitlines()[1:]:
        f = ln.split()
        if len(f) >= 6 and f[0] == ip:
            incomplete = f[2] == "0x0" or f[3] == "00:00:00:00:00:00"
            return {"dev": f[5], "state": "INCOMPLETE" if incomplete else "REACHABLE", "mac": "" if incomplete else f[3]}
    return None


def pick_route(routes, ip):
    """按路由表自己算：最长前缀优先，同前缀取表里排在前面的（和内核一致）。"""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return None
    best = None
    for r in routes:
        if r["dest"] == "default":
            plen, hit = 0, True
        else:
            try:
                n = ipaddress.ip_network(r["dest"], strict=False)
            except ValueError:
                continue
            plen, hit = n.prefixlen, a in n
        if hit and (best is None or plen > best[0]):
            best = (plen, r)
    return best[1] if best else None


def collect_net(ip, env=None):
    """收集服务器网络信息。拿不到的项留空，不报错。"""
    env = env or default_env()
    run, read, listdir = env["run"], env["read"], env["listdir"]
    info = {"available": False, "platform": os.name, "ifaces": [], "routes": [], "route": None, "neigh": None, "notes": []}
    addrs = parse_addr(run(["ip", "-4", "-o", "addr"]))
    names = listdir("/sys/class/net")
    states = {}
    for n in names:
        s = read(f"/sys/class/net/{n}/operstate")
        if s is not None:
            states[n] = s.strip()
    if not addrs:  # 没有 ip 命令：只能列网卡名
        info["notes"].append("no_ip_cmd")
    ifs = {}
    for a in addrs:
        d = ifs.setdefault(a["name"], {"name": a["name"], "addrs": [], "state": states.get(a["name"], "")})
        d["addrs"].append(a["cidr"])
    for n in names:
        if n != "lo" and n not in ifs and n in states:
            ifs[n] = {"name": n, "addrs": [], "state": states[n]}
    info["ifaces"] = [v for k, v in ifs.items() if k != "lo"]
    routes = parse_routes(run(["ip", "route"]))
    if not routes:
        routes = parse_proc_route(read("/proc/net/route"))
        if routes:
            info["notes"].append("route_from_proc")
    info["routes"] = routes
    if ip:
        rg = parse_route_get(run(["ip", "route", "get", ip]))
        if rg:
            info["route"] = rg
        else:
            r = pick_route(routes, ip)
            if r:
                info["route"] = {"dev": r["dev"], "src": r["src"], "via": "", "linkdown": r["linkdown"], "guess": True}
        info["neigh"] = parse_neigh(run(["ip", "neigh", "show", ip])) or parse_proc_arp(read("/proc/net/arp"), ip)
    info["available"] = bool(info["ifaces"] or routes)
    return info


def _same_subnet_ifaces(info, ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return []
    out = []
    for i in info["ifaces"]:
        for c in i["addrs"]:
            try:
                if a in ipaddress.ip_network(c, strict=False):
                    out.append(i)
                    break
            except ValueError:
                pass
    return out


def _is_down(i):
    return (i.get("state") or "").lower() in ("down", "lowerlayerdown", "notpresent")


# ---------------- 结论 ----------------
def conclusions(ctype, ports, info, ip, mqtt=None):
    """返回 [{level: bad|warn|ok|info, zh, th}]，最重要的排前面。
    mqtt：Bambu 登录测试结果 None / 'ok' / 'auth' / 'nostatus'。"""
    out = []

    def add(lvl, zh, th):
        out.append({"level": lvl, "zh": zh, "th": th})

    summ = summarize_ports(ports)
    ok_ports = [p["port"] for p in ports if p["kind"] == "ok"]
    info = info or {"ifaces": [], "route": None, "neigh": None}
    found_dead_route = False

    # 1 两块网卡同网段，路由走了断线的那块
    route = info.get("route") or {}
    dev = route.get("dev")
    same = _same_subnet_ifaces(info, ip) if ip else []
    dev_if = next((i for i in info["ifaces"] if i["name"] == dev), None)
    dev_down = bool(dev and (route.get("linkdown") or (dev_if and _is_down(dev_if))))
    if dev_down and summ != "open":
        good = [i for i in same if i["name"] != dev and not _is_down(i)]
        if len(same) >= 2 and good:
            found_dead_route = True
            gname = good[0]["name"]
            net = next((c for c in (dev_if or {}).get("addrs", [])), "")
            subnet = str(ipaddress.ip_network(net, strict=False)) if net else "x.x.x.0/24"
            add("bad",
                f"原因找到了：这台服务器（NAS）有两个网口在同一个网段（{subnet}），其中 {dev} 没插网线（断线），"
                f"可是系统路由表里走 {dev} 的那条排在前面，所以去 {ip} 的数据全从断线的 {dev} 发出去了，到不了打印机"
                f"（电脑和 Bambu Studio 走自己的网络，所以是通的）。\n"
                f"临时解决（重启后失效）：SSH 登录 NAS 执行  sudo ip route del {subnet} dev {dev}\n"
                f"永久解决：QNAP 控制台 → 网络与虚拟交换机 → 找到没插线的那个网口（{dev}），把它改成「DHCP」或停用，"
                f"不要给它填和 {gname} 同网段的固定 IP。\n"
                f"注意：千万不要动你现在用来打开这个系统的那个网口（{gname}），否则网页会打不开。",
                f"พบสาเหตุ: เซิร์ฟเวอร์ (NAS) มีพอร์ตเครือข่าย 2 ตัวอยู่วงเดียวกัน ({subnet}) และ {dev} ไม่ได้เสียบสาย (ลิงก์ดาวน์) "
                f"แต่ตารางเส้นทางของระบบใช้ {dev} ก่อน ข้อมูลที่ส่งไป {ip} จึงออกทางพอร์ตที่ไม่มีสาย ไปไม่ถึงเครื่องพิมพ์ "
                f"(คอมพิวเตอร์และ Bambu Studio ใช้เครือข่ายของตัวเอง จึงเชื่อมต่อได้)\n"
                f"แก้ชั่วคราว (หายเมื่อรีสตาร์ท): SSH เข้า NAS แล้วรัน  sudo ip route del {subnet} dev {dev}\n"
                f"แก้ถาวร: QNAP แผงควบคุม → Network & Virtual Switch → เลือกพอร์ตที่ไม่ได้เสียบสาย ({dev}) ตั้งเป็น DHCP หรือปิดใช้งาน "
                f"อย่าใส่ IP คงที่วงเดียวกับ {gname}\n"
                f"ข้อควรระวัง: ห้ามแตะพอร์ตที่ใช้เข้าระบบนี้อยู่ ({gname}) ไม่เช่นนั้นจะเปิดหน้าเว็บไม่ได้")
        else:
            add("warn",
                f"服务器去 {ip} 走的网口 {dev} 是断线状态（没插网线或交换机没通）。检查这个网口的网线，或把路由改到有线的那个网口。",
                f"เซิร์ฟเวอร์ส่งไป {ip} ผ่านพอร์ต {dev} ซึ่งลิงก์ดาวน์ (ไม่ได้เสียบสายหรือสวิตช์ไม่ติด) ตรวจสายของพอร์ตนี้ หรือเปลี่ยนเส้นทางไปพอร์ตที่ใช้งานได้")

    # 2 端口结果
    if summ == "noroute":
        add("bad",
            f"服务器「找不到主机」{ip}。如果电脑能连上这台打印机：① 路由器开了 AP 隔离 / 访客 Wi-Fi，有线的 NAS 访问不到无线设备；"
            f"② 打印机连在另一个路由器 / 另一个网段；③ NAS 的防火墙（QuFirewall）或 Docker 网络挡住了；④ 打印机 IP 变了，到打印机屏幕 设置 → 网络 确认。",
            f"เซิร์ฟเวอร์ 'หาโฮสต์ไม่พบ' {ip} ถ้าคอมพิวเตอร์เชื่อมต่อเครื่องพิมพ์ได้: ① เราเตอร์เปิด AP isolation / Wi-Fi แขก NAS ที่ใช้สายจึงเข้าอุปกรณ์ไร้สายไม่ได้ "
            f"② เครื่องพิมพ์อยู่คนละเราเตอร์ / คนละวงเครือข่าย ③ ไฟร์วอลล์ของ NAS (QuFirewall) หรือเครือข่าย Docker บล็อกอยู่ ④ IP ของเครื่องพิมพ์เปลี่ยน ดูที่หน้าจอเครื่องพิมพ์ ตั้งค่า → เครือข่าย")
    elif summ == "timeout":
        add("bad",
            f"连接 {ip} 全部超时（没有任何回应）。打印机可能关机 / 休眠，IP 填错，或中间有防火墙把包丢掉了（NAS 防火墙 QuFirewall、路由器隔离）。先确认打印机开着，再看屏幕上的 IP。",
            f"เชื่อมต่อ {ip} หมดเวลาทุกพอร์ต (ไม่มีการตอบกลับ) เครื่องพิมพ์อาจปิด/พักเครื่อง กรอก IP ผิด หรือมีไฟร์วอลล์ทิ้งแพ็กเก็ต (QuFirewall ของ NAS, การแยกเครือข่ายของเราเตอร์) ตรวจว่าเครื่องเปิดอยู่ และดู IP บนหน้าจอ")
    elif summ == "refused":
        if ctype in ("bambu", "auto", "none", "", None):
            add("bad",
                f"{ip} 这台设备在线，但所有打印机端口都拒绝连接。拓竹：到打印机屏幕 设置 → 网络 打开「局域网模式」（新固件还要开「开发者模式」）；"
                f"也可能是打印机没开机（别的设备占着这个 IP），或者这个 IP 根本不是打印机。",
                f"อุปกรณ์ที่ {ip} ออนไลน์ แต่ทุกพอร์ตของเครื่องพิมพ์ปฏิเสธการเชื่อมต่อ Bambu: เปิด 'โหมด LAN' ที่หน้าจอ ตั้งค่า → เครือข่าย (เฟิร์มแวร์ใหม่ต้องเปิด 'โหมดนักพัฒนา' ด้วย) "
                f"หรือเครื่องพิมพ์ปิดอยู่ (อุปกรณ์อื่นใช้ IP นี้) หรือ IP นี้ไม่ใช่เครื่องพิมพ์")
        else:
            add("bad",
                f"{ip} 这台设备在线，但打印机端口没开。确认连接方式选对了（Creality 原厂固件 9999；root 后 Moonraker 7125 / 4408），IP 是不是这台打印机。",
                f"อุปกรณ์ที่ {ip} ออนไลน์ แต่พอร์ตของเครื่องพิมพ์ไม่เปิด ตรวจว่าเลือกวิธีเชื่อมต่อถูก (Creality เฟิร์มแวร์เดิม 9999; หลัง root ใช้ Moonraker 7125 / 4408) และ IP ตรงกับเครื่องนี้")
    elif summ == "other":
        add("bad", f"连接 {ip} 出现其他网络错误（见下表的错误码）。", f"เชื่อมต่อ {ip} พบข้อผิดพลาดเครือข่ายอื่น (ดูรหัสในตารางด้านล่าง)")
    else:
        add("ok", f"网络是通的：{ip} 的 {'、'.join(str(p) for p in ok_ports)} 端口可以连上。",
            f"เครือข่ายปกติ: เชื่อมต่อ {ip} พอร์ต {', '.join(str(p) for p in ok_ports)} ได้")
        if 7125 in ok_ports or 4408 in ok_ports:
            add("info", "7125 / 4408 通：这是 Moonraker（Klipper / root 过的 Creality K1），连接方式选「Moonraker」或「自动识别」。",
                "พอร์ต 7125 / 4408 เปิด: เป็น Moonraker (Klipper / Creality K1 ที่ root แล้ว) เลือกวิธีเชื่อมต่อ 'Moonraker' หรือ 'ตรวจจับอัตโนมัติ'")
        if 9999 in ok_ports:
            add("info", "9999 通：这是 Creality 原厂固件（WebSocket），连接方式选「Creality」或「自动识别」。",
                "พอร์ต 9999 เปิด: เป็นเฟิร์มแวร์เดิมของ Creality (WebSocket) เลือกวิธีเชื่อมต่อ 'Creality' หรือ 'ตรวจจับอัตโนมัติ'")
        if 8883 in ok_ports:
            if mqtt == "auth":
                add("bad", "8883 通，但登录被拒：访问码不对。到打印机屏幕 设置 → 网络 查看访问码（每次重开局域网模式会变）。",
                    "พอร์ต 8883 เปิด แต่ล็อกอินถูกปฏิเสธ: รหัสเข้าถึงไม่ถูก ดูที่หน้าจอเครื่องพิมพ์ ตั้งค่า → เครือข่าย (เปลี่ยนทุกครั้งที่เปิดโหมด LAN ใหม่)")
            elif mqtt == "nostatus":
                add("bad", "8883 通、登录成功，但收不到打印机状态：序列号填错了。序列号在打印机 设置 → 设备信息。",
                    "พอร์ต 8883 เปิด ล็อกอินสำเร็จ แต่ไม่ได้รับสถานะ: หมายเลขซีเรียลผิด ดูที่ ตั้งค่า → ข้อมูลอุปกรณ์")
            elif mqtt == "ok":
                add("ok", "拓竹登录和状态都正常。", "Bambu เข้าสู่ระบบและรับสถานะได้ปกติ")
            else:
                add("info", "8883 通：这是拓竹打印机。填好序列号和访问码后点「测试连接」确认。",
                    "พอร์ต 8883 เปิด: เป็นเครื่อง Bambu กรอกซีเรียลและรหัสเข้าถึงแล้วกด 'ทดสอบการเชื่อมต่อ'")
        elif ctype == "bambu":
            add("bad", "拓竹的 8883 端口没通，其他端口通：这个 IP 可能不是拓竹，或没开局域网模式。",
                "พอร์ต 8883 ของ Bambu ไม่เปิด แต่พอร์ตอื่นเปิด: IP นี้อาจไม่ใช่ Bambu หรือยังไม่เปิดโหมด LAN")
    nb = info.get("neigh")
    if summ != "open" and not found_dead_route and nb and nb.get("state") in ("FAILED", "INCOMPLETE"):
        add("info", f"ARP 状态 {nb['state']}：服务器在网口 {nb.get('dev', '')} 上问不到这个 IP 的 MAC 地址，说明二层就不通。",
            f"สถานะ ARP {nb['state']}: เซิร์ฟเวอร์ถามหา MAC ของ IP นี้ที่พอร์ต {nb.get('dev', '')} ไม่ได้ แปลว่าชั้นลิงก์ยังไม่ถึงกัน")
    return out


def diagnose(ip, ctype="auto", timeout=2.0, connect=None, env=None, mqtt=None, with_net=True):
    ports = probe_all(ip, ctype, timeout, connect)
    info = collect_net(ip, env) if with_net else None
    return {"ip": ip, "ports": ports, "summary": summarize_ports(ports), "net": info,
            "conclusions": conclusions(ctype, ports, info, ip, mqtt)}


FAIL_MSGS = {
    "noroute": "找不到这台设备（No route to host）：服务器的网络到不了这个 IP。可能 IP 变了、打印机在另一个网段 / 访客 Wi-Fi，"
               "或 NAS 有两个网口在同一网段且其中一个没插线。点旁边的「网络诊断」看详细原因",
    "timeout": "连接超时：这个 IP 没有任何回应。确认打印机开机、IP 没填错、和 NAS 在同一个局域网。点旁边的「网络诊断」看详细原因",
    "refused": "这个 IP 的设备在线，但打印机端口都没开：拓竹请打开「局域网模式」，Creality / Klipper 请确认连接方式。点旁边的「网络诊断」看详细原因",
    "other": "连不上这个 IP（网络错误）。点旁边的「网络诊断」看详细原因",
    "open": "连不上这个 IP。点旁边的「网络诊断」看详细原因",
}


def fail_message(host, connect=None):
    """「测试连接」连不上时的具体原因（固定文字，方便翻译）。"""
    return FAIL_MSGS[summarize_ports(probe_all(host, "auto", 1.5, connect))]
