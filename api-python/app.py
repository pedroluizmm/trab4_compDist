"""Experimental adaptation of step5, with a shared contract and real cache bypass."""
import json
import os
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, request
import redis

app = Flask(__name__)
CACHE = os.environ.get("CACHE_ENABLED", "false").lower() == "true"
TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "5"))
# OFF creates no Redis connection pool and makes no Redis calls.
store = redis.Redis.from_url(os.environ["REDIS_URL"], socket_timeout=2,
                              socket_connect_timeout=2) if CACHE else None


def output(payload, status=200, cache=None):
    body = payload if isinstance(payload, str) else json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"))
    response = Response(body, status=status, content_type="application/json; charset=utf-8")
    if cache:
        response.headers["X-Cache"] = cache
    response.headers["X-Implementation"] = "python"
    return response


@app.get("/health")
def health():
    return output({"status": "ok", "implementation": "python", "cache_enabled": CACHE,
                   "workers": 2, "threads_per_worker": 4})


@app.get("/api/extract")
@app.get("/api/<path:legacy_url>")
def extract(legacy_url=None):
    url = request.args.get("url", "") if legacy_url is None else legacy_url
    if legacy_url and request.query_string:
        url += "?" + request.query_string.decode("utf-8")
    # Restrict the experiment to its immutable, controlled corpus.
    if not re.fullmatch(r"http://paginas/pagina(?:0[1-9]|10)\.html", url):
        return output({"error": "URL outside controlled corpus"}, 400)
    key = "t4:python:" + url
    try:
        if CACHE:
            cached = store.get(key)
            if cached is not None:
                return output(cached.decode("utf-8"), cache="HIT")
        page = requests.get(url, timeout=(TIMEOUT, TIMEOUT))
        page.raise_for_status()
        soup = BeautifulSoup(page.content, "html.parser")
        links = [{"text": " ".join(a.get_text().split()) or "[IMG]",
                  "href": urljoin(url, a["href"])} for a in soup.find_all("a", href=True)]
        body = json.dumps(links, ensure_ascii=False, separators=(",", ":"))
        if CACHE:
            store.set(key, body)
        return output(body, cache="MISS" if CACHE else "OFF")
    except redis.RedisError:
        return output({"error": "Redis unavailable"}, 503)
    except requests.RequestException:
        return output({"error": "Upstream unavailable"}, 502)
