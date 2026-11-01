"""各家 AI 接口的调用（只管发请求、读结果、出错时给清楚的原因）。选哪家、备用、记费用在 router.py。

文字：text(p, model, system, user, image_b64) → (文字, token 输入, token 输出)
出图：image(p, model, prompt, ref_png, aspect, n, edit) → [图片 bytes]
网络请求都用 requests.post / requests.get（测试里替换成假的）。密钥只放在请求头里，不写进地址、不写日志。
"""
import base64
import re
import time

import requests

from .errors import AIError

TIMEOUT = 120
IMG_TIMEOUT = 240
SIZES = {"1:1": (1024, 1024), "3:4": (768, 1024), "4:3": (1024, 768), "16:9": (1344, 768), "9:16": (768, 1344)}
OPENAI_SIZE = {"1:1": "1024x1024", "3:4": "1024x1536", "9:16": "1024x1536", "4:3": "1536x1024", "16:9": "1536x1024"}


def _err(r, what="AI"):
    try:
        txt = r.text[:300]
    except Exception:  # noqa: BLE001
        txt = ""
    code = getattr(r, "status_code", 0)
    kind = "rate" if code == 429 else "auth" if code in (401, 403) else "server" if code >= 500 else "client"
    return AIError(f"{what} 接口错误 {code}: {txt}", kind=kind, status=code)


def _post(url, what="AI", **kw):
    try:
        return requests.post(url, **kw)
    except requests.Timeout as e:
        raise AIError(f"连接 {what} 接口超时：{e}", kind="timeout") from e
    except requests.RequestException as e:
        raise AIError(f"连接 {what} 接口失败：{e}", kind="network") from e


def _get(url, what="AI", **kw):
    try:
        return requests.get(url, **kw)
    except requests.RequestException as e:
        raise AIError(f"连接 {what} 接口失败：{e}", kind="network") from e


def _json(r):
    try:
        return r.json()
    except Exception as e:  # noqa: BLE001
        raise AIError(f"AI 接口返回的内容看不懂：{e}", kind="server") from e


# ---------------- 文字（含看图） ----------------
def text(p, model, system, user, image_b64=None):
    style = p["style"]
    key = p["api_key"]
    if style == "anthropic":
        r = _post(p["base_url"] + "/v1/messages", headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                  json={"model": model, "max_tokens": 4000, "system": system,
                        "messages": [{"role": "user", "content": user if not image_b64 else [
                            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                            {"type": "text", "text": user}]}]}, timeout=TIMEOUT)
        if r.status_code != 200:
            raise _err(r)
        d = _json(r)
        u = d.get("usage") or {}
        return ("".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text"),
                int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0))
    if style == "gemini":
        parts = [{"text": user}]
        if image_b64:
            parts.insert(0, {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}})
        r = _post(f"{p['base_url']}/models/{model}:generateContent", headers={"x-goog-api-key": key, "content-type": "application/json"},
                  json={"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": parts}]}, timeout=TIMEOUT)
        if r.status_code != 200:
            raise _err(r)
        d = _json(r)
        out = "".join(pt.get("text", "") for c in d.get("candidates") or [] for pt in (c.get("content") or {}).get("parts") or [])
        u = d.get("usageMetadata") or {}
        if not out:
            raise AIError("AI 没有返回内容（可能被安全策略拦截）", kind="server")
        return out, int(u.get("promptTokenCount") or 0), int(u.get("candidatesTokenCount") or 0)
    # OpenAI 和兼容接口（DeepSeek、通义、其他）
    base = p["base_url"]
    url = base + ("/chat/completions" if base.endswith("/v1") or "deepseek" in base or base.endswith("compatible-mode/v1") else "/v1/chat/completions")
    body = {"model": model, "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": user if not image_b64 else [
                                             {"type": "text", "text": user},
                                             {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image_b64}}]}]}
    if p["id"] != "openai":
        body["temperature"] = 0.7
    r = _post(url, headers={"Authorization": f"Bearer {key}", "content-type": "application/json"}, json=body, timeout=TIMEOUT)
    if r.status_code != 200:
        raise _err(r)
    d = _json(r)
    try:
        out = d["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise AIError(f"AI 接口返回的内容看不懂：{str(d)[:200]}", kind="server") from e
    u = d.get("usage") or {}
    return out or "", int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)


# ---------------- 出图 ----------------
def _fetch(url):
    if url.startswith("data:"):
        return base64.b64decode(url.split(",", 1)[1])
    r = _get(url, "图片", timeout=120)
    if r.status_code != 200:
        raise _err(r, "图片下载")
    return r.content


def image(p, model, prompt, ref_png=None, aspect="1:1", n=1, edit=False):
    """返回 [图片 bytes]（n 张）。edit=True 时 ref_png 是参考图（产品抠图），要求保持产品不变。"""
    style, key, base = p["style"], p["image_key"], p["image_base"]
    n = max(1, min(int(n or 1), 4))
    if style == "openai":
        size = OPENAI_SIZE.get(aspect, "1024x1024")
        hdr = {"Authorization": f"Bearer {key}"}
        if edit and ref_png:
            data = {"model": model, "prompt": prompt, "size": size, "n": str(n)}
            if p.get("image_quality"):
                data["quality"] = p["image_quality"]
            if "gpt-image" in model:
                data["input_fidelity"] = "high"
            files = {"image": ("product.png", ref_png, "image/png")}
            r = _post(f"{base}/images/edits", "图片 AI", headers=hdr, files=files, data=data, timeout=IMG_TIMEOUT)
            if r.status_code != 200 and "input_fidelity" in (getattr(r, "text", "") or ""):
                data.pop("input_fidelity", None)
                r = _post(f"{base}/images/edits", "图片 AI", headers=hdr, files=files, data=data, timeout=IMG_TIMEOUT)
        else:
            data = {"model": model, "prompt": prompt, "size": size, "n": n}
            if p.get("image_quality"):
                data["quality"] = p["image_quality"]
            r = _post(f"{base}/images/generations", "图片 AI", headers=hdr, json=data, timeout=IMG_TIMEOUT)
        if r.status_code != 200:
            raise _err(r, "图片 AI")
        out = []
        for item in _json(r).get("data") or []:
            if item.get("b64_json"):
                out.append(base64.b64decode(item["b64_json"]))
            elif item.get("url"):
                out.append(_fetch(item["url"]))
        if not out:
            raise AIError("图片 AI 没有返回图片", kind="server")
        return out
    if style == "gemini":
        out = []
        for _ in range(n):
            parts = [{"text": prompt}]
            if ref_png:
                parts.append({"inline_data": {"mime_type": "image/png", "data": base64.b64encode(ref_png).decode()}})
            body = {"contents": [{"parts": parts}], "generationConfig": {"responseModalities": ["IMAGE", "TEXT"],
                                                                          "imageConfig": {"aspectRatio": aspect}}}
            r = _post(f"{base}/models/{model}:generateContent", "图片 AI", headers={"x-goog-api-key": key, "content-type": "application/json"},
                      json=body, timeout=IMG_TIMEOUT)
            if r.status_code != 200 and "imageConfig" in (getattr(r, "text", "") or ""):
                body["generationConfig"].pop("imageConfig", None)
                r = _post(f"{base}/models/{model}:generateContent", "图片 AI", headers={"x-goog-api-key": key, "content-type": "application/json"},
                          json=body, timeout=IMG_TIMEOUT)
            if r.status_code != 200:
                raise _err(r, "图片 AI")
            got = None
            for c in _json(r).get("candidates") or []:
                for part in (c.get("content") or {}).get("parts") or []:
                    d = part.get("inlineData") or part.get("inline_data")
                    if d and d.get("data"):
                        got = base64.b64decode(d["data"])
                        break
                if got:
                    break
            if not got:
                raise AIError("图片 AI 没有返回图片（可能被安全策略拦截，换个场景或提示词再试）", kind="server")
            out.append(got)
        return out
    if style == "fal":
        w, h = SIZES.get(aspect, SIZES["1:1"])
        body = {"prompt": prompt, "num_images": n}
        if edit and ref_png:
            body["image_url"] = "data:image/png;base64," + base64.b64encode(ref_png).decode()
            body["aspect_ratio"] = aspect
        else:
            body["image_size"] = {"width": w, "height": h}
        r = _post(f"{base}/{model}", "图片 AI", headers={"Authorization": f"Key {key}", "content-type": "application/json"},
                  json=body, timeout=IMG_TIMEOUT)
        if r.status_code != 200:
            raise _err(r, "图片 AI")
        urls = [i.get("url") for i in _json(r).get("images") or [] if i.get("url")]
        if not urls:
            raise AIError("图片 AI 没有返回图片", kind="server")
        return [_fetch(u) for u in urls[:n]]
    if style == "replicate":
        inp = {"prompt": prompt, "aspect_ratio": aspect, "output_format": "png"}
        if edit and ref_png:
            inp["input_image"] = "data:image/png;base64," + base64.b64encode(ref_png).decode()
        else:
            inp["num_outputs"] = n
        hdr = {"Authorization": f"Bearer {key}", "content-type": "application/json", "Prefer": "wait"}
        r = _post(f"{base}/models/{model}/predictions", "图片 AI", headers=hdr, json={"input": inp}, timeout=IMG_TIMEOUT)
        if r.status_code not in (200, 201):
            raise _err(r, "图片 AI")
        d = _json(r)
        t0 = time.time()
        while d.get("status") not in ("succeeded", "failed", "canceled") and (d.get("urls") or {}).get("get") and time.time() - t0 < IMG_TIMEOUT:
            time.sleep(2)
            g = _get(d["urls"]["get"], "图片 AI", headers={"Authorization": f"Bearer {key}"}, timeout=30)
            if g.status_code != 200:
                raise _err(g, "图片 AI")
            d = _json(g)
        if d.get("status") in ("failed", "canceled"):
            raise AIError(f"图片 AI 生成失败：{str(d.get('error') or d.get('status'))[:200]}", kind="server")
        o = d.get("output")
        urls = o if isinstance(o, list) else [o] if o else []
        if not urls:
            raise AIError("图片 AI 没有返回图片", kind="server")
        return [_fetch(u) for u in urls[:n]]
    raise AIError(f"{p['zh']} 不能出图", kind="cap")


def ping(p, kind="text"):
    """「测试连接」：用最便宜的方式确认密钥能用（文字发一句话；只能出图的服务商查一下账号 / 模型）。"""
    if kind == "text":
        return text(p, p["text_model"], "Reply with OK.", "ping")
    if p["style"] == "fal":
        r = _get("https://api.fal.ai/v1/models?limit=1", "图片 AI", headers={"Authorization": f"Key {p['image_key']}"}, timeout=20)
    elif p["style"] == "replicate":
        r = _get(f"{p['image_base']}/account", "图片 AI", headers={"Authorization": f"Bearer {p['image_key']}"}, timeout=20)
    elif p["style"] == "gemini":
        r = _get(f"{p['image_base']}/models/{p['image_model']}", "图片 AI", headers={"x-goog-api-key": p["image_key"]}, timeout=20)
    else:
        r = _get(f"{p['image_base']}/models", "图片 AI", headers={"Authorization": f"Bearer {p['image_key']}"}, timeout=20)
    if r.status_code != 200:
        raise _err(r, "图片 AI")
    return "OK", 0, 0


def scrub(msg, *keys):
    """出错信息里万一带了密钥，打码。"""
    msg = str(msg or "")
    for k in keys:
        if k and len(k) > 6:
            msg = msg.replace(k, "******")
    return re.sub(r"(sk-|key=)[A-Za-z0-9_\-]{8,}", r"\1******", msg)
