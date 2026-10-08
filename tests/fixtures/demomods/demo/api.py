from flask import Blueprint, jsonify
bp = Blueprint("m_demo", __name__)


@bp.get("/api/m/demo/hello")
def hello():
    return jsonify({"hi": "demo"})


@bp.post("/api/m/demo/secret")
def secret():
    return jsonify({"ok": True})
