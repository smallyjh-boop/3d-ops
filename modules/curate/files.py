"""模型文件：扩展用浏览器里原站的登录状态下载、上传到 ERP，直接存进产品的模型库文件夹（data/products/<编号>/source_files/，
core/modellib 的约定：模型库自动登记、分析尺寸 / 体积 / 估算克数和时长、读切好的 3MF 里的时间和克数）。只存一份，不另外建文件库。"""
import os
import re
import uuid

MODEL_KINDS = ("stl", "3mf", "obj", "step", "stp", "zip", "gcode", "f3d", "scad", "blend")
MAX_FILE_BYTES = 500 * 1024 * 1024


def kind_of(name):
    n = (name or "").lower()
    if n.endswith(".gcode.3mf"):
        return "gcode"
    ext = os.path.splitext(n)[1].lstrip(".")
    return ext


def safe_name(name):
    return re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", os.path.basename(str(name or "file")))[:120].strip(". ") or "file"


def save_to_product(pid, name, stream):
    """把上传的文件流存进产品的 source_files。返回 (文件名, 字节数)。"""
    from core import store
    d = os.path.join(store.product_dir(pid), "source_files")
    os.makedirs(d, exist_ok=True)
    name = safe_name(name)
    dest = os.path.join(d, name)
    if os.path.exists(dest):
        stem, ext = os.path.splitext(name)
        dest = os.path.join(d, f"{stem}_{uuid.uuid4().hex[:5]}{ext}")
    tmp = dest + ".part"
    n = 0
    with open(tmp, "wb") as f:
        while True:
            chunk = stream.read(256 * 1024)
            if not chunk:
                break
            n += len(chunk)
            if n > MAX_FILE_BYTES:
                f.close()
                os.remove(tmp)
                raise ValueError(f"文件太大（超过 {MAX_FILE_BYTES // 1048576} MB）")
            f.write(chunk)
    if n < 16:
        os.remove(tmp)
        raise ValueError("文件是空的")
    os.replace(tmp, dest)
    return os.path.basename(dest), n
