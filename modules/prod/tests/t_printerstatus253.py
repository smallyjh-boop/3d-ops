# v2.53：打印机状态显示 —— Creality 原厂固件的 err 字段（errcode 0 = 没错误，不显示红字）、拓竹断线报错显示中文
import os as _os, sys
APP = _os.environ["T3D_APP"]; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
from core import printers as p
ok(p._creality_err({"errcode": 0, "key": 0, "value": ""}) == "", "Creality errcode 0 = no error")
ok(p._creality_err(None) == "" and p._creality_err(0) == "" and p._creality_err({}) == "", "empty err")
ok(p._creality_err({"errcode": 2001, "key": 5, "value": "nozzle"}) == "错误码 2001：nozzle", "real Creality error shown")
msg = p._human_err(OSError(113, "No route to host"))
ok("Errno" not in msg and "关机" in msg, f"no-route error in plain words: {msg}")
ok("Errno" not in p._human_err(ConnectionRefusedError(111, "Connection refused")), "refused in plain words")
sys.exit(1 if E_ else 0)
