# 回归测试（自动从开发时的测试脚本转换）。由 tests/run_all.py 调用，不要直接在正式数据上运行。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, io, json
os.environ["LH_DATA_DIR"]=T+"/v20"; sys.path.insert(0,APP)
import app as A
c=A.app.test_client(); c.post("/api/auth/login",json={"username":"boss","password":"secret1"})
r=c.post("/api/print-files",data={"product_id":"3DP0001","files":[(open(T+"/v12/p1.gcode.3mf","rb"),"p1.gcode.3mf"),(open(T+"/v12/k1.gcode","rb"),"k1.gcode")]},content_type="multipart/form-data")
print(r.status_code, json.dumps(r.get_json()["results"],ensure_ascii=False))
r=c.post("/api/print-files",data={"files":[(open(T+"/v20/print_files/"+[n for n in os.listdir(T+"/v20/print_files") if n.endswith(".3mf")][0],"rb"),"3DP0002_test.gcode.3mf")]},content_type="multipart/form-data")
print(r.status_code, r.get_json().get("detected"), r.get_json().get("printer"), r.get_json().get("per_plate"))
