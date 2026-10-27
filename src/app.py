"""Local control app: a small Flask server for the window in gui.py.

Binds to 127.0.0.1 only. Every POST needs the per-launch token embedded in
the page, and the Host header must be local, so a website open in your browser
can't drive the bot through localhost.
"""

import os
import secrets
from pathlib import Path

from flask import Flask, jsonify, request, abort, Response

import runlog
import settings
from controller import SessionController

ROOT = Path(__file__).resolve().parent.parent
PAGE = (Path(__file__).parent / "ui.html")


def create_app(controller: SessionController | None = None) -> Flask:
    app = Flask(__name__)
    ctl = controller or SessionController()
    token = secrets.token_urlsafe(24)

    @app.before_request
    def guard():
        host = (request.host or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            abort(403)
        if request.method == "POST" and request.headers.get("X-App-Token") != token:
            abort(403)

    @app.get("/")
    def index():
        return Response(PAGE.read_text().replace("__TOKEN__", token),
                        mimetype="text/html")

    @app.get("/api/status")
    def status():
        return jsonify(ctl.status())

    @app.post("/api/start")
    def start():
        ok = ctl.start(**settings.run_kwargs())
        return jsonify({"started": ok}), (200 if ok else 409)

    @app.post("/api/stop")
    def stop():
        return jsonify({"stopping": ctl.stop()})

    @app.get("/api/feed")
    def feed():
        return jsonify(runlog.recent(min(int(request.args.get("limit", 50)), 200)))

    @app.get("/api/stats")
    def stats():
        return jsonify(runlog.stats())

    @app.get("/api/settings")
    def get_settings():
        return jsonify(settings.read())

    @app.post("/api/settings")
    def post_settings():
        if ctl.is_running():
            return jsonify({"error": "stop the session before changing settings"}), 409
        try:
            return jsonify(settings.write(request.get_json(force=True) or {}))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.get("/api/setup")
    def setup():
        return jsonify({
            "anthropic_key": os.environ.get("ANTHROPIC_API_KEY", "").startswith("sk-ant-"),
            "telegram": bool(os.environ.get("TELEGRAM_BOT_TOKEN")
                             and os.environ.get("TELEGRAM_CHAT_ID")),
            "tinder_session": (runlog.home() / "tinder-session").exists(),
            "env_file": (ROOT / ".env").exists(),
        })

    return app
