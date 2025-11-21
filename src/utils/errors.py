from __future__ import annotations
from flask import jsonify

def api_error(message: str, status: int = 400):
    return jsonify({"error": message}), status
