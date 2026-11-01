# v2.53.0：打印机网络诊断（core/netdiag.py）——端口分类、网卡 / 路由解析、qvs0 / qvs2 案例、Windows 降级、接口权限
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, errno, socket, re, sqlite3
D = T + "/m_netdiag253"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, netdiag

IP = "192.168.31.166"

# ---- 1 端口分类（假 socket）
class FakeSock:
    def close(self): pass
def mk(behaviour):
    def connect(addr, timeout=None):
        b = behaviour(addr[1])
        if b is None:
            return FakeSock()
        raise b
    return connect
ref = ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused")
tmo = socket.timeout("timed out")
nor = OSError(errno.EHOSTUNREACH, "No route to host")
oth = OSError(errno.EPERM, "Operation not permitted")
ok(netdiag.probe_port(IP, 1, connect=mk(lambda p: None))["kind"] == "ok", "open port -> ok")
ok(netdiag.probe_port(IP, 1, connect=mk(lambda p: ref))["kind"] == "refused", "refused")
ok(netdiag.probe_port(IP, 1, connect=mk(lambda p: tmo))["kind"] == "timeout", "timeout")
r = netdiag.probe_port(IP, 1, connect=mk(lambda p: nor))
ok(r["kind"] == "noroute" and r["errno"] == errno.EHOSTUNREACH, "no route")
r = netdiag.probe_port(IP, 1, connect=mk(lambda p: oth))
ok(r["kind"] == "other" and r["errno"] == errno.EPERM, "other keeps errno")
ok(netdiag.probe_port(IP, 1, connect=mk(lambda p: OSError(10061, "x")))["kind"] == "refused", "windows 10061 refused")
ok(netdiag.probe_port(IP, 1, connect=mk(lambda p: OSError(None, "Network is unreachable")))["kind"] == "noroute", "unreachable by text")
pl = [p["port"] for p in netdiag.probe_all(IP, "auto", connect=mk(lambda p: ref))]
ok(set(pl) >= {8883, 990, 7125, 4408, 4409, 9999, 80}, f"auto probes all ports {pl}")
pl = [p["port"] for p in netdiag.probe_all(IP, "bambu", connect=mk(lambda p: ref))]
ok(8883 in pl and 990 in pl and 9999 not in pl and 80 in pl, "bambu ports")
ok(netdiag.summarize_ports(netdiag.probe_all(IP, "auto", connect=mk(lambda p: ref))) == "refused", "all refused summary")
ok(netdiag.summarize_ports(netdiag.probe_all(IP, "auto", connect=mk(lambda p: tmo))) == "timeout", "all timeout summary")
ok(netdiag.summarize_ports(netdiag.probe_all(IP, "auto", connect=mk(lambda p: None if p == 9999 else ref))) == "open", "one open summary")

# ---- 2 老板 NAS 的真实案例
ADDR = """1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever preferred_lft forever
5: qvs0    inet 192.168.31.2/24 brd 192.168.31.255 scope global qvs0\\       valid_lft forever preferred_lft forever
7: qvs2    inet 192.168.31.200/24 brd 192.168.31.255 scope global qvs2\\       valid_lft forever preferred_lft forever
"""
ROUTE = """default via 192.168.31.1 dev qvs2
192.168.31.0/24 dev qvs0 proto kernel scope link src 192.168.31.2 linkdown
192.168.31.0/24 dev qvs2 proto kernel scope link src 192.168.31.200
"""
OUT = {
    ("ip", "-4", "-o", "addr"): ADDR,
    ("ip", "route"): ROUTE,
    ("ip", "route", "get", IP): f"{IP} dev qvs0 src 192.168.31.2 uid 0 \n    cache \n",
    ("ip", "neigh", "show", IP): f"{IP} dev qvs0  FAILED\n",
}
FILES = {"/sys/class/net/qvs0/operstate": "down\n", "/sys/class/net/qvs2/operstate": "up\n", "/sys/class/net/lo/operstate": "unknown\n"}
env = {"run": lambda cmd: OUT.get(tuple(cmd)), "read": lambda p: FILES.get(p),
       "listdir": lambda p: ["lo", "qvs0", "qvs2"] if p == "/sys/class/net" else []}
info = netdiag.collect_net(IP, env)
names = {i["name"]: i for i in info["ifaces"]}
ok(set(names) == {"qvs0", "qvs2"}, f"ifaces (lo hidden): {list(names)}")
ok(names["qvs0"]["state"] == "down" and names["qvs2"]["state"] == "up" and names["qvs2"]["addrs"] == ["192.168.31.200/24"], "iface state + addr")
ok(info["routes"][1]["linkdown"] and info["routes"][1]["dev"] == "qvs0", "linkdown route parsed")
ok(info["route"]["dev"] == "qvs0" and info["neigh"]["state"] == "FAILED" and info["neigh"]["dev"] == "qvs0", "route get + neigh")
d = netdiag.diagnose(IP, "bambu", connect=mk(lambda p: nor), env=env)
c = d["conclusions"][0]
ok(c["level"] == "bad" and "qvs0" in c["zh"] and "sudo ip route del 192.168.31.0/24 dev qvs0" in c["zh"], "dead-interface conclusion with temp command")
ok("DHCP" in c["zh"] and "不要动" in c["zh"] and "qvs2" in c["zh"], "permanent QNAP steps + warning")
ok("sudo ip route del 192.168.31.0/24 dev qvs0" in c["th"] and not re.search(r"[一-鿿]", c["th"]), "thai version, no Chinese")
ok(all(not re.search(r"[一-鿿]", x["th"]) for x in d["conclusions"]), "all thai conclusions Chinese-free")
# 没有 ip route get：靠路由表自己推，顺序在前的先用
env2 = dict(env, run=lambda cmd: None if tuple(cmd)[:3] == ("ip", "route", "get") else OUT.get(tuple(cmd)))
i2 = netdiag.collect_net(IP, env2)
ok(i2["route"]["dev"] == "qvs0" and i2["route"].get("guess"), "fallback route pick = first same-prefix route")
# 删掉坏路由后（路由走 qvs2）+ 超时 -> 不再报断线结论
OUT2 = dict(OUT); OUT2[("ip", "route", "get", IP)] = f"{IP} dev qvs2 src 192.168.31.200 uid 0\n"; OUT2[("ip", "neigh", "show", IP)] = ""
env3 = dict(env, run=lambda cmd: OUT2.get(tuple(cmd)))
d3 = netdiag.diagnose(IP, "auto", connect=mk(lambda p: tmo), env=env3)
ok(not any("原因找到了" in x["zh"] for x in d3["conclusions"]) and "超时" in d3["conclusions"][0]["zh"], "healthy route + timeout -> generic timeout hint")

# ---- 3 其他结论
def concl(summ_behaviour, ctype="auto", mqtt=None, e=env3):
    return netdiag.diagnose(IP, ctype, connect=mk(summ_behaviour), env=e, mqtt=mqtt)["conclusions"]
cs = concl(lambda p: nor)
ok(any("AP 隔离" in x["zh"] and "QuFirewall" in x["zh"] for x in cs), "no route -> isolation / firewall hints")
cs = concl(lambda p: ref, "bambu")
ok(any("局域网模式" in x["zh"] for x in cs), "refused (bambu) -> LAN mode")
cs = concl(lambda p: None if p == 8883 else ref, "bambu", mqtt="auth")
ok(any("访问码" in x["zh"] and x["level"] == "bad" for x in cs), "8883 open + auth fail -> access code")
cs = concl(lambda p: None if p == 8883 else ref, "bambu", mqtt="nostatus")
ok(any("序列号" in x["zh"] for x in cs), "connected but no status -> serial")
cs = concl(lambda p: None if p == 9999 else ref, "auto")
ok(any("9999" in x["zh"] and "原厂" in x["zh"] for x in cs), "creality 9999 stock firmware")
cs = concl(lambda p: None if p in (7125, 4408) else ref, "auto")
ok(any("Moonraker" in x["zh"] for x in cs), "7125/4408 moonraker")

# ---- 4 Windows / Mac 降级：什么都读不到也不能报错
envw = {"run": lambda cmd: None, "read": lambda p: None, "listdir": lambda p: []}
iw = netdiag.collect_net(IP, envw)
ok(iw["available"] is False and iw["ifaces"] == [] and iw["route"] is None, "windows fallback: empty info, no crash")
dw = netdiag.diagnose(IP, "auto", connect=mk(lambda p: tmo), env=envw)
ok(dw["conclusions"] and dw["summary"] == "timeout", "windows fallback still gives conclusion")
# /proc/net/route 兜底（没有 ip 命令的 Linux）
PROC = "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\nbr0\t00000000\t0101A8C0\t0003\t0\t0\t0\t00000000\nbr0\t0001A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\n"
ip_ = netdiag.collect_net("192.168.1.9", {"run": lambda c: None, "read": lambda p: PROC if p == "/proc/net/route" else None, "listdir": lambda p: []})
ok(ip_["route"] and ip_["route"]["dev"] == "br0" and ip_["routes"][1]["dest"] == "192.168.1.0/24", "/proc/net/route fallback")
ok(netdiag.parse_proc_arp("IP address HW type Flags HW address Mask Device\n1.2.3.4 0x1 0x0 00:00:00:00:00:00 * eth0\n", "1.2.3.4")["state"] == "INCOMPLETE", "proc arp incomplete")

# ---- 5 测试连接的具体报错
real = socket.create_connection
try:
    def cc(addr, timeout=None, **k): raise nor
    socket.create_connection = cc
    ok("No route to host" in netdiag.fail_message("10.9.9.9"), "fail_message noroute")
    def cc2(addr, timeout=None, **k): raise ref
    socket.create_connection = cc2
    ok("在线" in netdiag.fail_message("10.9.9.9"), "fail_message refused")
    def cc3(addr, timeout=None, **k): raise tmo
    socket.create_connection = cc3
    ok("超时" in netdiag.fail_message("10.9.9.9"), "fail_message timeout")
    from core import printers as pr
    try:
        pr.detect({"host": "10.9.9.9"}); ok(False, "detect should raise")
    except ValueError as e:
        ok("超时" in str(e) and "连不上这个 IP。请确认" not in str(e), "detect error is specific")
finally:
    socket.create_connection = real

# ---- 6 接口：老板有网络信息，生产角色没有
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("pong", "secret123", "production", "Pong")
config.save_config({"printers": [{"name": "P1S", "code": "P1", "conn": {"type": "bambu", "host": "127.0.0.1"}}]})
orig = netdiag.collect_net
netdiag.collect_net = lambda ip, e=None: orig(ip, env)
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
P = A.app.test_client(); P.post("/api/auth/login", json={"username": "pong", "password": "secret123"})
r = C.post("/api/printers/0/netdiag", json={}); j = r.get_json()
ok(r.status_code == 200 and j["net"] and j["ports"] and j["conclusions"], f"owner gets net info ({r.status_code})")
r = P.post("/api/printers/0/netdiag", json={})
ok(r.status_code == 403, f"production role cannot call it ({r.status_code})")
from core import auth
_io = auth.is_owner; auth.is_owner = lambda: False
try:
    r = C.post("/api/printers/0/netdiag", json={}); j = r.get_json()
finally:
    auth.is_owner = _io
ok(r.status_code == 200 and j["net"] is None and j["ports"], "non-owner: ports yes, network details no")
ok("qvs0" not in str(j), "production response has no interface names")
ok(C.post("/api/printers/9/netdiag", json={}).status_code == 400, "bad index")
netdiag.collect_net = orig

print("DONE", "FAIL" if E_ else "PASS")
sys.exit(1 if E_ else 0)
