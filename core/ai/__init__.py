"""AI 接口统一管理（v2.53）。系统里所有 AI 调用都从这里走：

    from core import ai
    ai.text(ai.for_task(cfg, "copy"), system, user, image_b64=None)     文字 / 看图（core.ai_copy.call 也是走这里）
    ai.image(cfg, prompt, ref_png=None, aspect="1:1", n=1, task="scene") 出图
    ai.can(cfg, "assembly")                                               (能不能用, 原因)：按钮灰掉 / 提示用

每个任务在「系统 → AI 接口」里选服务商 + 模型 + 备用顺序；出错 / 限流 / 超时自动换下一个；
每次调用记用量和费用（core/ai/usage.py），可以设每天 / 每月上限。
服务商：Claude、OpenAI、Gemini、DeepSeek、通义千问、其他 OpenAI 兼容接口；出图：OpenAI、Gemini、Flux（fal.ai / Replicate）。
"""
from . import catalog, conf, usage  # noqa: F401
from .errors import AIError  # noqa: F401
from .router import can, candidates, ensure_migrated, estimate_image, estimate_text, image, test, text  # noqa: F401

TASKS = catalog.TASKS


def for_task(cfg, task):
    """给 cfg 标上任务（复制一份，不改原来的）。老的 ai_copy.call(cfg, …) 写法不用改参数。"""
    d = dict(cfg or {})
    d["_ai_task"] = task
    return d


def ready(cfg, task="general"):
    """这个任务现在有没有能用的 AI（填了密钥）。"""
    return can(cfg, task, "text" if catalog.TASKS.get(task, ("text",))[0] != "image" else "image")[0]


def ai_copy_json(cfg, system, user, image_b64=None, strict=False):
    """调用 + 读 JSON（和 core.ai_copy.call 一样会被老测试替换掉的那条路：走 ai_copy.call / _request）。"""
    from .. import ai_copy
    fn = ai_copy._request if strict and image_b64 else ai_copy.call
    return ai_copy.extract_json(fn(cfg, system, user, image_b64))
