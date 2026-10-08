"""AI 客服模块的接口（Blueprint 在 logic/api.py）。/api/cs/… 软件界面用；/api/v1/cs/… 浏览器扩展用。"""
from .logic import data as _data
from .logic.api import bp  # noqa: F401

_data.init()          # 自己的数据表（模块关着也建好，打开时不用重启）
PREFIXES = ["/api/cs/", "/api/v1/cs/"]
