"""商品 360 的接口：GET /api/p360/<SKU 或产品编号>（右边抽屉一次取完）。"""
from flask import Blueprint

from web.common import *  # noqa: F401,F403
from modules.p360 import logic

bp = Blueprint("m_p360", __name__)
PREFIXES = ["/api/p360/"]
PATTERNS = []


@bp.get("/api/p360/<target>")
def p360_view(target):
    try:
        return jsonify(logic.view(target, auth.current_user()))
    except logic.NotFound as e:
        return jsonify({"error": str(e), "error_th": f"ไม่พบสินค้าหรือ SKU: {target}", "not_found": True}), 404
