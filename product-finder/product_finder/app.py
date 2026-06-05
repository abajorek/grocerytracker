"""Flask dashboard (local or deployed).

Local:    flask --app product_finder.app run   (or  python -m product_finder.app)
Deployed: gunicorn product_finder.app:app      (see DEPLOY.md / render.yaml)

Open the site, type a query, get a good/better/best answer with cited quotes.
Recent queries are cached in-memory so you don't re-spend API calls on a
refresh. When APP_PASSWORD is set, the whole site is gated behind a single
password (recommended for any public deployment, since searches spend your
Claude credits)."""

import os
import logging
from flask import Flask, render_template, request, Response

from .pipeline import run_search
from . import config as cfg

log = logging.getLogger("app")

# query (lowercased) + mock flag -> Recommendation, for the session lifetime.
_CACHE = {}


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")

    @app.before_request
    def _password_gate():
        password = os.getenv("APP_PASSWORD")
        if not password:
            return None  # no password configured -> open (fine for local use)
        auth = request.authorization
        if auth and auth.password == password:
            return None
        return Response(
            "Authentication required.", 401,
            {"WWW-Authenticate": 'Basic realm="Product Finder"'},
        )

    @app.route("/", methods=["GET"])
    def index():
        return render_template(
            "index.html",
            result=None,
            error=None,
            reddit_ok=cfg.reddit_available(),
            claude_ok=cfg.claude_available(),
        )

    @app.route("/search", methods=["POST"])
    def search():
        query = (request.form.get("query") or "").strip()
        mock = request.form.get("mock") == "1"
        error = None
        result = None
        if not query:
            error = "Type something to search for."
        else:
            key = (query.lower(), mock)
            if key in _CACHE:
                result = _CACHE[key]
            else:
                try:
                    result = run_search(query, mock=mock)
                    _CACHE[key] = result
                except Exception as e:  # noqa: BLE001
                    error = str(e)
        return render_template(
            "index.html",
            result=result.to_dict() if result else None,
            error=error,
            query=query,
            reddit_ok=cfg.reddit_available(),
            claude_ok=cfg.claude_available(),
        )

    return app


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="127.0.0.1", port=5000, debug=True)
