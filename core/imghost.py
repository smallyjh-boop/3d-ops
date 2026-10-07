"""图床上传：Lazada 导入表格只接受图片网址，所以先把处理好的图片传到图床拿到网址。"""
import base64
import os

import requests


class HostError(Exception):
    pass


def upload_imgbb(api_key, path):
    if not api_key:
        raise HostError("还没有填写 imgbb 图床密钥（设置页）")
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    try:
        r = requests.post(
            "https://api.imgbb.com/1/upload",
            data={"key": api_key, "image": b64, "name": os.path.splitext(os.path.basename(path))[0]},
            timeout=120,
        )
    except requests.RequestException as e:
        raise HostError(f"连接图床失败：{e}") from e
    if r.status_code != 200:
        raise HostError(f"图床错误 {r.status_code}: {r.text[:200]}")
    data = r.json().get("data") or {}
    url = data.get("url")
    if not url:
        raise HostError("图床没有返回网址")
    return url
