import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, io, zipfile
D=T+"/v20"
os.environ["LH_DATA_DIR"]=D; sys.path.insert(0,APP)
def cube(sx,sy,sz,ox=0):
    v=[(ox,0,0),(ox+sx,0,0),(ox+sx,sy,0),(ox,sy,0),(ox,0,sz),(ox+sx,0,sz),(ox+sx,sy,sz),(ox,sy,sz)]
    t=[(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    return "<mesh><vertices>"+"".join(f'<vertex x="{a}" y="{b}" z="{c}"/>' for a,b,c in v)+"</vertices><triangles>"+"".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a,b,c in t)+"</triangles></mesh>"
xml='<?xml version="1.0"?><model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources>'+f'<object id="1" name="桌面" type="model">{cube(120,80,5)}</object><object id="2" name="桌腿" type="model">{cube(10,10,60,200)}</object>'+'</resources><build><item objectid="1"/><item objectid="2"/></build></model>'
buf=io.BytesIO(); z=zipfile.ZipFile(buf,"w"); z.writestr("3D/3dmodel.model",xml); z.writestr("Metadata/plate_1.png",b"\x89PNG\r\n\x1a\nfake"); z.close(); KIT=buf.getvalue()
import app as A
c=A.app.test_client()
r=c.post("/api/products/3DP0001/models",data={"files":[(io.BytesIO(KIT),"桌子套件.3mf"),(open(T+"/cat.stl","rb"),"cat.stl")]},content_type="multipart/form-data")
print("seed",r.status_code,len(r.get_json()["items"]))
r=c.post("/api/products/3DP0001/images",data={"files":[(open(T+"/prod.jpg","rb"),"p1.jpg"),(open(T+"/prod2.jpg","rb"),"p2.jpg")]},content_type="multipart/form-data")
print("imgs",r.status_code,len(r.get_json()["images"]))
