#!/usr/bin/env python3
"""Studio server: static files + POST /levels.json so Save ships to the phone."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import time

ROOT = Path(__file__).resolve().parent
LEVELS = ROOT / "levels.json"
INDEX = ROOT / "index.html"
PORT = 8771


def jam_level_colors(item):
    return int(((item or {}).get("spec") or {}).get("colors") or 0)


def sync_embedded_levels(payload):
    """Keep EMBEDDED_LEVELS identical to disk so file:// cannot be older than levels.json."""
    if not INDEX.exists():
        return
    text = INDEX.read_text(encoding="utf-8")
    needle = "const EMBEDDED_LEVELS = "
    start = text.find(needle)
    if start < 0:
        return
    json_start = start + len(needle)
    try:
        _, end_rel = json.JSONDecoder().raw_decode(text[json_start:])
    except json.JSONDecodeError:
        return
    blob = json.dumps(payload, separators=(",", ":"))
    INDEX.write_text(text[:json_start] + blob + text[json_start + end_rel :], encoding="utf-8")


def write_catalog(data):
    if isinstance(data, list):
        levels = data
    elif isinstance(data, dict) and isinstance(data.get("levels"), list):
        levels = data["levels"]
    else:
        raise ValueError("catalog")
    if LEVELS.exists():
        try:
            old = json.loads(LEVELS.read_text(encoding="utf-8"))
            old_levels = old["levels"] if isinstance(old, dict) else old
            old_jam = {
                str(x.get("id")): x
                for x in old_levels
                if str((x or {}).get("id", "")).startswith("cjam")
            }
            rest = [x for x in levels if not str((x or {}).get("id", "")).startswith("cjam")]
            incoming_jam = [x for x in levels if str((x or {}).get("id", "")).startswith("cjam")]
            kept = []
            for item in incoming_jam:
                key = str(item.get("id"))
                prev = old_jam.get(key)
                if prev and jam_level_colors(item) < jam_level_colors(prev):
                    kept.append(prev)
                else:
                    kept.append(item)
            levels = rest + kept
        except Exception:
            pass
    payload = {"rev": int(time.time() * 1000), "levels": levels}
    LEVELS.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    try:
        sync_embedded_levels(payload)
    except Exception:
        pass


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/levels.json":
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        try:
            text = raw.decode("utf-8")
            stripped = text.lstrip()
            if stripped.startswith("{") or stripped.startswith("["):
                payload = json.loads(text)
            else:
                from urllib.parse import parse_qs, unquote
                qs = parse_qs(text, keep_blank_values=True)
                blob = (qs.get("levels") or [""])[0]
                payload = json.loads(unquote(blob))
            write_catalog(payload)
        except Exception:
            self.send_error(400, "Invalid catalog")
            return
        self.send_response(204)
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()

    def end_headers(self):
        path = getattr(self, "path", "") or ""
        path = path.split("?", 1)[0]
        if path in ("/", "/index.html", "/levels.json"):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        try:
            self._cors()
        except Exception:
            pass
        super().end_headers()


if __name__ == "__main__":
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("Serving Car Sort on http://0.0.0.0:%s/" % PORT, flush=True)
    httpd.serve_forever()
