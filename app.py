from __future__ import annotations
from flask import Flask, request
from config import settings
from src.routes.health import bp as health_bp
from src.routes.threads import bp as threads_bp

import logging
import time

def create_app() -> Flask:
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    )

    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(health_bp, url_prefix="")
    app.register_blueprint(threads_bp, url_prefix="/v1/threads")

    @app.before_request
    def start_timer():
        request.start_time = time.time()

    @app.after_request
    def log_request(response):
        duration = time.time() - request.start_time
        ip = request.headers.get('X-Real-IP', request.remote_addr)
        method = request.method
        path = request.path
        status = response.status_code

        logging.info(f"{ip} {method} {path} {status} {duration:.3f}s")
        return response

    @app.teardown_request
    def teardown_request(error):
        if error:
            logging.exception(f"Unhandled exception: {error}")

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host=settings.HOST, port=settings.PORT, debug=(settings.FLASK_ENV=="development"))