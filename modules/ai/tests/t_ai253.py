# AI 接口统一管理（v2.53）：每家服务商的请求格式 / 结果解析（假 HTTP）、出错自动换备用、不能看图 / 不能出图的拒绝、
# 用量和费用记录、上限（提醒 / 硬上限）、旧设置迁移（旧键继续有效）、密钥打码、设置页 / 用量页接口、权限。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import base64, io, json, os, shutil, sqlite3, sys
D = T + "/m_ai253"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0


def ok(b, m):
    global E_
    print(("OK  " if b else "ERR ") + m)
    E_ += (not b)


import requests
from PIL import Image
import app as A
from core import ai, ai_copy, config, db, diag
from core.ai import conf, router, usage

db.create_user("boss", "secret123", "owner", "Boss")
db.create_user("lister", "secret123", "listing", "Lister")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
L = A.app.test_client(); L.post("/api/auth/login", json={"username": "lister", "password": "secret123"})


# ---------------- 假 HTTP ----------------
class R:
    def __init__(self, code=200, data=None, content=b"", text=""):
        self.status_code, self._d, self.content = code, data, content
        self.text = text or (json.dumps(data) if data is not None else "")

    def json(self):
        return self._d


CALLS, PLAN = [], []         # PLAN：按顺序返回的假响应（函数 url, kw → R）


def fake_post(url, **kw):
    CALLS.append(("POST", url, kw))
    f = PLAN.pop(0) if PLAN else (lambda u, k: R(500, {"error": "no plan"}))
    return f(url, kw)


def fake_get(url, **kw):
    CALLS.append(("GET", url, kw))
    f = PLAN.pop(0) if PLAN else (lambda u, k: R(200, {}, content=PNG))
    return f(url, kw)


requests.post, requests.get = fake_post, fake_get
buf = io.BytesIO(); Image.new("RGB", (64, 48), (200, 30, 30)).save(buf, "PNG"); PNG = buf.getvalue()
B64 = base64.b64encode(PNG).decode()
anth_ok = lambda u, k: R(200, {"content": [{"type": "text", "text": '{"a": 1}'}], "usage": {"input_tokens": 1000000, "output_tokens": 0}})
oai_ok = lambda u, k: R(200, {"choices": [{"message": {"content": '{"b": 2}'}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
gem_ok = lambda u, k: R(200, {"candidates": [{"content": {"parts": [{"text": '{"c": 3}'}]}}], "usage": {}, "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3}})


def P(cfg_extra=None, **providers):
    cfg = config.load_config()
    cfg.update(cfg_extra or {})
    cfg["ai_providers"] = {k: v for k, v in providers.items()}
    return cfg


# ---------------- 文字：每家的请求格式 ----------------
cfg = P(anthropic={"api_key": "sk-ant-SECRET-1234567890"})
CALLS.clear(); PLAN[:] = [anth_ok]
out = ai.text(ai.for_task(cfg, "copy"), "SYS", "USER", B64)
m, url, kw = CALLS[-1]
ok(out == '{"a": 1}' and url == "https://api.anthropic.com/v1/messages" and kw["headers"]["x-api-key"] == "sk-ant-SECRET-1234567890"
   and kw["json"]["system"] == "SYS" and kw["json"]["messages"][0]["content"][0]["type"] == "image", "anthropic request + image block")
row = db.conn().execute("SELECT * FROM ai_usage ORDER BY id DESC LIMIT 1").fetchone()
ok(row["task"] == "copy" and row["provider"] == "anthropic" and row["tokens_in"] == 1000000 and abs(row["cost_thb"] - 110) < 1e-6 and row["ok"] == 1,
   f"usage logged with cost from price table {dict(row)}")

cfg = P({"ai_provider": "openai", "ai_model": ""}, openai={"api_key": "sk-oai-1234567890ab"})
CALLS.clear(); PLAN[:] = [oai_ok]
ai.text(ai.for_task(cfg, "general"), "S", "U")
m, url, kw = CALLS[-1]
ok(url == "https://api.openai.com/v1/chat/completions" and kw["headers"]["Authorization"] == "Bearer sk-oai-1234567890ab"
   and "temperature" not in kw["json"] and kw["json"]["model"] == "gpt-4.1-mini", f"openai request {url} {kw['json'].get('model')}")

cfg = P({"ai_provider": "gemini", "ai_model": "gem-x"}, gemini={"api_key": "g-key-1234567890"})
CALLS.clear(); PLAN[:] = [gem_ok]
out = ai.text(ai.for_task(cfg, "general"), "S", "U", B64)
m, url, kw = CALLS[-1]
ok(out == '{"c": 3}' and url.endswith("/models/gem-x:generateContent") and kw["headers"]["x-goog-api-key"] == "g-key-1234567890" and "key" not in (kw.get("params") or {})
   and kw["json"]["systemInstruction"]["parts"][0]["text"] == "S" and "inline_data" in kw["json"]["contents"][0]["parts"][0], "gemini request (key in header, image inline)")
row = db.conn().execute("SELECT * FROM ai_usage ORDER BY id DESC LIMIT 1").fetchone()
ok(row["tokens_in"] == 7 and row["tokens_out"] == 3 and row["kind"] == "vision", "gemini token usage parsed")

for pid, base, expect in (("deepseek", "", "https://api.deepseek.com/chat/completions"),
                          ("qwen", "", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"),
                          ("openai_compatible", "https://my.relay.example/v1", "https://my.relay.example/v1/chat/completions")):
    cfg = P({"ai_provider": pid, "ai_model": "m-1"}, **{pid: {"api_key": "k-1234567890", "base_url": base}})
    CALLS.clear(); PLAN[:] = [oai_ok]
    ai.text(ai.for_task(cfg, "general"), "S", "U")
    ok(CALLS[-1][1] == expect and CALLS[-1][2]["json"]["temperature"] == 0.7, f"{pid} → {CALLS[-1][1]}")

# 旧写法：只有旧键（没进新结构）也能用；DeepSeek 填了 claude 模型名 → 说清楚
legacy = {"ai_provider": "deepseek", "ai_api_key": "k", "ai_model": "claude-x"}
try:
    ai_copy._request(legacy, "s", "u", None); ok(False, "deepseek + claude model")
except ai_copy.AIError as e:
    ok("DeepSeek" in str(e), "deepseek needs its own model name")

# ---------------- 出错自动换备用 ----------------
cfg = P({"ai_tasks": {"cs_draft": {"chain": [{"p": "anthropic", "m": ""}, {"p": "openai", "m": "gpt-x"}]}}},
        anthropic={"api_key": "sk-ant-1234567890"}, openai={"api_key": "sk-oai-1234567890"})
n0 = usage.max_id()
CALLS.clear(); PLAN[:] = [lambda u, k: R(429, {"error": "rate limited"}), oai_ok]
out = ai.text(ai.for_task(cfg, "cs_draft"), "S", "U")
rows = db.conn().execute("SELECT * FROM ai_usage WHERE id>? ORDER BY id", (n0,)).fetchall()
ok(out == '{"b": 2}' and len(CALLS) == 2 and [r["ok"] for r in rows] == [0, 1] and rows[1]["fallback"] == 1 and rows[1]["model"] == "gpt-x",
   f"429 → fallback to next provider {[dict(r) for r in rows]}")
ok("rate" in rows[0]["error"] or "429" in rows[0]["error"], "error row keeps reason")
CALLS.clear(); PLAN[:] = [lambda u, k: (_ for _ in ()).throw(requests.Timeout("slow")), oai_ok]
ok(ai.text(ai.for_task(cfg, "cs_draft"), "S", "U") == '{"b": 2}', "timeout → fallback")
CALLS.clear(); PLAN[:] = [lambda u, k: R(500, {}, text="boom"), lambda u, k: R(503, {}, text="down")]
try:
    ai.text(ai.for_task(cfg, "cs_draft"), "S", "U"); ok(False, "all fail")
except ai.AIError as e:
    ok("Claude" in str(e) and "OpenAI" in str(e), f"all failed → both reasons {e}")
# 密钥不进出错信息
CALLS.clear(); PLAN[:] = [lambda u, k: R(401, {}, text="bad key sk-ant-1234567890"), lambda u, k: R(401, {}, text="bad")]
try:
    ai.text(ai.for_task(cfg, "cs_draft"), "S", "U")
except ai.AIError as e:
    ok("sk-ant-1234567890" not in str(e), "key scrubbed from error")

# ---------------- 能力：不能看图的拒绝 ----------------
cfg = P({"ai_provider": "deepseek", "ai_model": "ds-chat", "ai_api_key": ""}, deepseek={"api_key": "k-1234567890"})
for t in ("assembly", "recog"):
    okk, why = ai.can(cfg, t, "vision")
    ok(not okk and "DeepSeek" in why and "看图" in why, f"{t}: deepseek can't see images → {why}")
try:
    ai_copy._request(ai.for_task(cfg, "recog"), "s", "u", B64); ok(False, "strict vision")
except ai_copy.AIError as e:
    ok("DeepSeek" in str(e) and e.kind == "cap", "strict image call refused with clear message")
CALLS.clear(); PLAN[:] = [oai_ok]
ai_copy.call(ai.for_task(cfg, "kit"), "s", "u", B64)
ok(isinstance(CALLS[-1][2]["json"]["messages"][1]["content"], str), "vision-optional task → text-only on DeepSeek (old behaviour)")
# 看图任务：填了 Claude 的密钥时默认用 Claude
cfg2 = P({"ai_provider": "deepseek", "ai_model": "ds-chat"}, deepseek={"api_key": "k-1234567890"}, anthropic={"api_key": "sk-ant-1234567890"})
ok(conf.chain(cfg2, "assembly")[0][0] == "anthropic" and conf.chain(cfg2, "copy")[0][0] == "deepseek", "vision tasks default to Claude")
ok(ai.can(cfg2, "assembly", "vision")[0], "assembly OK with Claude key")
# 通义：vl 模型能看图
ok("vision" in ai.catalog.model_caps("qwen", "qwen-vl-max") and "vision" not in ai.catalog.model_caps("qwen", "qwen-plus"), "qwen vl caps")
ok(ai.catalog.model_caps("deepseek", "x", ["text", "vision"]) == ["text", "vision"], "manual caps override")
# 出图：文字服务商不能出图
cfg3 = P({"image_provider": "openai", "ai_tasks": {"scene": {"chain": [{"p": "anthropic", "m": ""}]}}}, anthropic={"api_key": "sk-ant-1234567890"})
okk, why = ai.can(cfg3, "scene", "image")
ok(not okk and "不能出图" in why, f"anthropic can't make images → {why}")

# ---------------- 出图：每家的请求格式 ----------------
img_ok_oai = lambda u, k: R(200, {"data": [{"b64_json": B64}]})
cfg = P({"image_provider": "openai"}, openai={"api_key": "sk-oai-1234567890", "image_model": "gpt-image-1"})
CALLS.clear(); PLAN[:] = [img_ok_oai]
r = ai.image(cfg, "a desk", PNG, "16:9", 1, task="scene")
m, url, kw = CALLS[-1]
ok(r["edited"] and url.endswith("/images/edits") and "image" in kw["files"] and kw["data"]["size"] == "1536x1024" and kw["data"]["input_fidelity"] == "high",
   "openai image edit (multipart, aspect → size)")
CALLS.clear(); PLAN[:] = [img_ok_oai]
r = ai.image(cfg, "empty bg", None, "3:4", 1, task="scene_bg")
ok(not r["edited"] and CALLS[-1][1].endswith("/images/generations") and CALLS[-1][2]["json"]["size"] == "1024x1536", "openai generations")
row = db.conn().execute("SELECT * FROM ai_usage ORDER BY id DESC LIMIT 1").fetchone()
ok(row["kind"] == "image" and row["images"] == 1 and abs(row["cost_thb"] - 0.5) < 1e-6, "image cost logged")

cfg = P({"image_provider": "gemini"}, gemini={"api_key": "g-1234567890"})
CALLS.clear(); PLAN[:] = [lambda u, k: R(200, {"candidates": [{"content": {"parts": [{"inlineData": {"data": B64}}]}}]})]
r = ai.image(cfg, "p", PNG, "9:16", 1, task="scene")
ok(r["edited"] and CALLS[-1][2]["json"]["generationConfig"]["imageConfig"]["aspectRatio"] == "9:16" and r["images"][0] == PNG, "gemini image with aspect + reference")

cfg = P({"image_provider": "fal"}, fal={"api_key": "fal-1234567890"})
CALLS.clear(); PLAN[:] = [lambda u, k: R(200, {"images": [{"url": "https://cdn.example/x.png"}]}), lambda u, k: R(200, {}, content=PNG)]
r = ai.image(cfg, "p", PNG, "1:1", 1, task="scene")
ok(r["edited"] and CALLS[0][1] == "https://fal.run/fal-ai/flux-pro/kontext" and CALLS[0][2]["headers"]["Authorization"] == "Key fal-1234567890"
   and CALLS[0][2]["json"]["image_url"].startswith("data:image/png;base64,") and r["images"][0] == PNG, "fal kontext edit with reference")
CALLS.clear(); PLAN[:] = [lambda u, k: R(200, {"images": [{"url": "https://cdn.example/x.png"}]}), lambda u, k: R(200, {}, content=PNG)]
r = ai.image(P({"image_provider": "fal"}, fal={"api_key": "fal-1234567890", "edit_model": "-"}), "p", None, "4:3", 1, task="scene")
ok(not r["edited"] and CALLS[0][1] == "https://fal.run/fal-ai/flux/schnell" and CALLS[0][2]["json"]["image_size"] == {"width": 1024, "height": 768}, "fal schnell generate")

cfg = P({"image_provider": "replicate"}, replicate={"api_key": "r8-1234567890", "edit_model": "-"})
CALLS.clear(); PLAN[:] = [lambda u, k: R(201, {"status": "starting", "urls": {"get": "https://api.replicate.com/v1/predictions/abc"}}),
                          lambda u, k: R(200, {"status": "succeeded", "output": ["https://r.example/o.png"]}),
                          lambda u, k: R(200, {}, content=PNG)]
import core.ai.providers as _prov
_prov.time.sleep = lambda s: None
r = ai.image(cfg, "p", PNG, "1:1", 1, task="scene")
ok(not r["edited"] and CALLS[0][1] == "https://api.replicate.com/v1/models/black-forest-labs/flux-schnell/predictions"
   and CALLS[0][2]["headers"]["Prefer"] == "wait" and CALLS[1][1].endswith("/predictions/abc") and r["images"][0] == PNG,
   "replicate: no edit model → generate (caller composites), polls prediction")

# 出图出错 → 下一个
cfg = P({"image_provider": "fal", "ai_tasks": {"scene": {"chain": [{"p": "fal", "m": "fal-ai/flux/schnell"}, {"p": "openai", "m": ""}]}}},
        fal={"api_key": "fal-1234567890", "edit_model": "-"}, openai={"api_key": "sk-oai-1234567890"})
CALLS.clear(); PLAN[:] = [lambda u, k: R(500, {"detail": "x"}), lambda u, k: R(200, {"images": [{"url": "https://cdn.example/x.png"}]}), lambda u, k: R(200, {}, content=PNG)]
r = ai.image(cfg, lambda edit: "EDIT" if edit else "GEN", PNG, "1:1", 1, task="scene")
ok(CALLS[0][1].endswith("/images/edits") and CALLS[0][2]["data"]["prompt"] == "EDIT" and r["provider"] == "fal" and not r["edited"]
   and CALLS[1][2]["json"]["prompt"] == "GEN", f"image: edit-capable provider first, on error next one with background prompt {r['provider']}")

# ---------------- 上限 ----------------
cfg = P({"ai_tasks": {"adtext": {"daily_calls": 1, "hard": True}}}, anthropic={"api_key": "sk-ant-1234567890"})
CALLS.clear(); PLAN[:] = [anth_ok]
ai.text(ai.for_task(cfg, "adtext"), "s", "u")
try:
    ai.text(ai.for_task(cfg, "adtext"), "s", "u"); ok(False, "hard cap")
except ai.AIError as e:
    ok(e.kind == "budget" and "上限" in str(e), f"hard cap stops calls: {e}")
cfg["ai_tasks"]["adtext"]["hard"] = False
PLAN[:] = [anth_ok]
ok(ai.text(ai.for_task(cfg, "adtext"), "s", "u") and usage.check(cfg, "adtext")[1], "soft cap only warns")
cfg = P({"ai_limits": {"daily_thb": 1, "hard": True}}, anthropic={"api_key": "sk-ant-1234567890"})
ok(not usage.check(cfg, "copy")[0], "overall daily THB cap (already spent > 1 THB today)")

# ---------------- 旧设置迁移 ----------------
old = {"ai_provider": "deepseek", "ai_api_key": "ds-OLD-123456789", "ai_model": "ds-chat", "image_provider": "gemini",
       "image_api_key": "gm-OLD-123456789", "image_model": "gem-img", "recog_ai_daily": 50}
mig = conf.migrate(old, "ds-fast")
ok(mig["ai_v2"] == 1 and mig["ai_tasks"]["cs_draft"]["chain"] == [{"p": "deepseek", "m": "ds-fast"}] and mig["ai_tasks"]["recog"]["daily_calls"] == 50,
   "migration: cs model → task chain, recog daily → cap")
after = {**old, **mig}
ok(conf.provider(after, "deepseek")["api_key"] == "ds-OLD-123456789" and conf.provider(after, "gemini")["image_key"] == "gm-OLD-123456789"
   and conf.provider(after, "gemini")["image_model"] == "gem-img" and conf.chain(after, "copy") == [("deepseek", "ds-chat")]
   and conf.chain(after, "scene") == [("gemini", "")], "old keys still work after migration")
ok(conf.migrate(after) == {}, "migrates only once")
# 同一家文字 / 出图用不同的密钥（旧设置）：出图用旧的出图密钥
o2 = {"ai_provider": "openai_compatible", "ai_base_url": "https://api.openai.com/v1", "ai_api_key": "sk-text-1234567890",
      "image_provider": "openai", "image_api_key": "sk-img-1234567890", "image_api_base": "https://relay.example/v1"}
ok(conf.provider(o2, "openai")["image_key"] == "sk-img-1234567890" and conf.provider(o2, "openai")["image_base"] == "https://relay.example/v1",
   "legacy image key + relay base kept")
# 用旧键改密钥 → 同步进新结构
config.save_config({"ai_provider": "anthropic", "ai_providers": {"anthropic": {"api_key": "sk-ant-NEW-12345678"}}})
config.save_config({"ai_api_key": "sk-ant-NEWER-1234567"})
ok(config.load_config()["ai_providers"]["anthropic"]["api_key"] == "sk-ant-NEWER-1234567", "legacy key write syncs to new structure")
# 首次启动自动迁移（真实 config）
router._mig["done"] = False
config.save_config({"ai_v2": 0})
router.ensure_migrated()
ok(config.load_config().get("ai_v2") == 1 and config.load_config().get("ai_migrated"), "ensure_migrated on first use")

# ---------------- 设置页接口：密钥打码 ----------------
d = C.get("/api/ai/settings").get_json()
txt = json.dumps(d)
an = next(p for p in d["providers"] if p["id"] == "anthropic")
ok("sk-ant-NEWER-1234567" not in txt and an["has_key"] and an["key_mask"] == "sk-…4567", f"settings view masks keys {an['key_mask']}")
ok("sk-ant-NEWER-1234567" not in json.dumps(C.get("/api/config").get_json()), "/api/config does not leak ai_providers keys")
r = C.post("/api/ai/settings", json={"providers": {"anthropic": {"api_key": an["key_mask"], "text_model": "m-z"},
                                                   "fal": {"api_key": "fal-NEW-1234567890"}},
                                     "tasks": {"scene": {"chain": [{"p": "fal", "m": ""}, {"p": "nope"}], "daily_thb": 20, "hard": True}},
                                     "limits": {"monthly_thb": 500}, "prices": {"anthropic:m-z": {"in": 5, "out": 9}, "bogus": {"in": 1}},
                                     "default_text": {"p": "anthropic", "m": "m-z"}}).get_json()
cfgd = config.load_config()
ok(cfgd["ai_providers"]["anthropic"]["api_key"] == "sk-ant-NEWER-1234567" and cfgd["ai_providers"]["anthropic"]["text_model"] == "m-z", "masked key not overwritten")
ok(cfgd["ai_providers"]["fal"]["api_key"] == "fal-NEW-1234567890" and cfgd["ai_tasks"]["scene"]["chain"] == [{"p": "fal", "m": ""}]
   and cfgd["ai_tasks"]["scene"]["daily_thb"] == 20 and cfgd["ai_limits"]["monthly_thb"] == 500 and "bogus" not in cfgd["ai_prices"]
   and cfgd["ai_model"] == "m-z" and cfgd["ai_api_key"] == "sk-ant-NEWER-1234567", "settings saved (tasks, limits, prices, default, legacy mirror)")
ok(abs(usage.cost(cfgd, "anthropic", "m-z", 1000000, 1000000) - 14) < 1e-6, "per-model price overrides provider price")
C.post("/api/ai/settings", json={"providers": {"fal": {"api_key": "-"}}})
ok(config.load_config()["ai_providers"]["fal"]["api_key"] == "", "'-' clears a key")
safe = diag.bundle("x", [], config.load_config(), ())
import zipfile
ok("sk-ant-NEWER" not in zipfile.ZipFile(io.BytesIO(safe)).read("config_no_secrets.json").decode(), "diagnostics zip strips nested keys")
# 测试连接
CALLS.clear(); PLAN[:] = [anth_ok]
t = C.post("/api/ai/test", json={"provider": "anthropic"}).get_json()
ok(t["ok"] and CALLS[-1][1].endswith("/v1/messages"), f"test connection {t}")
PLAN[:] = [lambda u, k: R(401, {}, text="invalid x-api-key sk-ant-NEWER-1234567")]
t = C.post("/api/ai/test", json={"provider": "anthropic"}).get_json()
ok(not t["ok"] and "401" in t["msg"] and "sk-ant-NEWER-1234567" not in t["msg"], "test connection error without key")
ok(not C.post("/api/ai/test", json={"provider": "fal"}).get_json()["ok"], "no key → test says so")
# 用量页
u = C.get("/api/ai/usage?days=7").get_json()
ok(u["total"]["n"] > 5 and len(u["by_day"]) == 7 and any(x["task"] == "cs_draft" for x in u["by_task"]) and u["recent"] and "tasks" in u, "usage stats")
u2 = C.get("/api/ai/usage?days=7&task=cs_draft&provider=openai").get_json()
ok(u2["total"]["n"] >= 1 and all(r["task"] == "cs_draft" and r["provider"] == "openai" for r in u2["recent"]), "usage filters")
# 权限
ok(L.get("/api/ai/settings").status_code == 403 and L.get("/api/ai/usage").status_code == 403, "staff cannot open AI settings / usage")
mods = C.get("/api/modules").get_json()
mods = mods.get("modules", mods) if isinstance(mods, dict) else mods
ok(any(m.get("id") == "ai" for m in mods), "ai module listed")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
