# v2.26：GitHub 在线更新（用本机假的 GitHub 接口）、外网地址（Tailscale）设置、密钥不发回浏览器
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, json, threading, http.server, io, zipfile, urllib.parse
D = T + "/v226"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E = 0
def ok(b, m):
    global E; print(("OK  " if b else "ERR ") + m); E += (not b)

# 假的程序目录（升级只写到这里，不碰真的程序）
FAKE = D + "/fakeapp"
os.makedirs(FAKE + "/core"); os.makedirs(FAKE + "/static")
open(FAKE + "/app.py", "w").write('VERSION = "2.26.0"\n')
open(FAKE + "/core/x.py", "w").write("old\n")
open(FAKE + "/static/a.js", "w").write("old\n")

def mkzip(ver):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        p = "smallyjh-boop-3d-ops-abc1234/"
        z.writestr(p + "app.py", f'VERSION = "{ver}"\n')
        z.writestr(p + "core/x.py", "new\n")
        z.writestr(p + "static/a.js", "new\n")
        z.writestr(p + "tests/cases/t.py", "should be skipped\n")
        z.writestr(p + "requirements.txt", "")
    return b.getvalue()

README = """更新记录
   v2.27.1：修好了几个问题
   · 修复 A
   · 修复 B

   v2.27.0：新功能
   · 功能 C

   v2.26.0：外网访问
   · 旧的
"""
SEEN = {"auth": [], "paths": []}
SHA = "a" * 40
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        SEEN["auth"].append(self.headers.get("Authorization"))
        u = urllib.parse.urlparse(self.path); SEEN["paths"].append(u.path)
        if self.headers.get("Authorization") != "Bearer good-token":
            self.send_response(401); self.end_headers(); return
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/repos/smallyjh-boop/3d-ops/commits/main":
            body = json.dumps({"sha": SHA}).encode()
        elif u.path == "/repos/smallyjh-boop/3d-ops/contents/app.py" and q.get("ref") == [SHA]:
            body = b'import os\nVERSION = "2.27.1"   # x\n'
        elif u.path == "/repos/smallyjh-boop/3d-ops/contents/README.txt" and q.get("ref") == [SHA]:
            body = README.encode()
        elif u.path == "/repos/smallyjh-boop/3d-ops/zipball/" + SHA:
            body = mkzip("2.27.1")
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

import app as A
from core import updater, sysadmin, config, auth
updater.API = f"http://127.0.0.1:{srv.server_address[1]}"
sysadmin.APP_DIR = FAKE
restarts = []
sysadmin.restart_later = lambda delay=2.0: restarts.append(1)
C = A.app.test_client()

# 默认仓库、令牌没填
st = C.get("/api/system/update").get_json()
ok(st["repo"] == "smallyjh-boop/3d-ops" and not st["token_set"] and st["current"] == "2.26.0" and not st["available"], f"default status {st}")
st = C.post("/api/system/update/check", json={}).get_json()
ok("令牌不对" in st["error"] and not st["available"], f"no token → 401 explained {st['error']}")
# 保存令牌：不会发回浏览器
r = C.post("/api/config", json={"update_token": "good-token"}).get_json()
ok(r["config"]["update_token"] == "******", "token masked in save response")
g = C.get("/api/config").get_json()
ok(g["config"]["update_token"] == "******" and config.load_config()["update_token"] == "good-token", "token masked for owner, kept on NAS")
C.post("/api/config", json={"update_token": "******"})
ok(config.load_config()["update_token"] == "good-token", "****** keeps saved token")
st = C.post("/api/system/update/check", json={}).get_json()
ok(st["available"] and st["latest"] == "2.27.1" and not st["error"], f"check finds main branch version {st}")
ok([n["version"] for n in st["notes"]] == ["2.27.1", "2.27.0"] and st["notes"][0]["points"] == ["修复 A", "修复 B"], f"notes {st['notes']}")
ok(SEEN["auth"][-1] == "Bearer good-token", "token sent to GitHub")
# 仓库名写错
C.post("/api/config", json={"update_repo": "https://github.com/smallyjh-boop/nope.git"})
st = C.post("/api/system/update/check", json={}).get_json()
ok("找不到仓库" in st["error"] and SEEN["paths"][-1] == "/repos/smallyjh-boop/nope/commits/main", f"repo url normalized, 404 explained {st['error']}")
C.post("/api/config", json={"update_repo": "bad repo"})
ok("拥有者/仓库名" in C.post("/api/system/update/check", json={}).get_json()["error"], "bad repo format")
C.post("/api/config", json={"update_repo": "smallyjh-boop/3d-ops"})
C.post("/api/system/update/check", json={})
# 升级
r = C.post("/api/system/update/apply", json={})
d = r.get_json()
ok(r.status_code == 200 and d["from"] == "2.26.0" and d["to"] == "2.27.1" and "GitHub" in d["source"], f"apply {d}")
ok(open(FAKE + "/core/x.py").read() == "new\n" and sysadmin.current_version() == "2.27.1", "files replaced")
ok(not os.path.exists(FAKE + "/tests"), "tests folder skipped")
ok(os.path.exists(os.path.join(D, "backups", d["app_backup"])), "app backed up first")
ok(not os.path.exists(D + "/tmp/github_update.zip"), "download removed")
ok(restarts == [] or not sysadmin.IN_DOCKER, "restart only in docker")
st = C.get("/api/system/update").get_json()
ok(not st["available"], "now up to date")
r = C.post("/api/system/update/apply", json={})
ok(r.status_code == 400 and "已经是最新" in r.get_json()["error"], "apply when up to date")
r = C.post("/api/system/update/apply", json={"tag": "../../evil"})
ok(r.status_code == 400, "bad tag rejected")
srv.shutdown()

# 外网地址
r = C.post("/api/system/remote", json={"remote_url": "100.81.34.58:8790/"}).get_json()
ok(r["remote_url"] == "http://100.81.34.58:8790", f"remote url normalized {r}")
g = C.get("/api/system/remote").get_json()
ok(g["remote_url"] == "http://100.81.34.58:8790" and isinstance(g["tailscale_ips"], list), f"remote get {g}")
ok(C.post("/api/system/remote", json={"remote_url": "http://a b"}).status_code == 400, "bad url rejected")
v = C.get("/api/version")
ok(v.headers.get("Access-Control-Allow-Origin") == "*", "version CORS for remote test")
# 员工不能用
ok(isinstance(sysadmin.tailscale_ips(), list), "tailscale_ips safe")
print("ERRORS", E)
