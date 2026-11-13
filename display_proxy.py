#!/usr/bin/env python3
"""Sits between Caddy and Terminus for GET /api/display.

Terminus still handles the request (so battery/RSSI/firmware are recorded), but the
image in the response is replaced:
  * a wake at the normal refresh interval (timer)  -> the home page (weather)
  * a wake well before the interval (button press)  -> the next page in the rotation
Firmware 1.5.12 doesn't report why it woke, so timing is the only signal.

The refresh_rate in the response is rewritten too: the home page keeps the device's
Terminus refresh rate (1 h), any other page gets page_refresh_s (5 min) so the device
falls back to the home page soon after a button press. Button detection compares
against the refresh rate we actually sent last time.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, "config.json"))).get("display", {})
UPSTREAM = CFG.get("upstream", "http://127.0.0.1:2301")
ROTATION = CFG.get("rotation", ["weather", "house", "solar"])
EARLY_S = CFG.get("button_margin_s", 60)   # wake this much earlier than refresh = button press
PAGE_REFRESH_S = CFG.get("page_refresh_s", 300)  # sleep after showing a non-home page
URIS_FILE = os.path.join(BASE, "screens.json")
STATE_FILE = os.path.join(BASE, "display_state.json")


def load_state():
    try:
        return json.load(open(STATE_FILE))
    except (OSError, ValueError):
        return {}


def save_state(st):
    tmp = STATE_FILE + ".tmp"
    json.dump(st, open(tmp, "w"))
    os.replace(tmp, STATE_FILE)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(fmt % args, flush=True)

    def do_GET(self):
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "connection")}
        req = urllib.request.Request(UPSTREAM + self.path, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                status, body, ctype = r.status, r.read(), r.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as e:
            status, body, ctype = e.code, e.read(), e.headers.get("Content-Type", "application/json")
        except Exception as e:
            self.send_error(502, str(e))
            return

        if status == 200 and self.path.startswith("/api/display"):
            try:
                body = self.rewrite(json.loads(body)).encode()
            except Exception as e:  # never break the device over this
                print(f"rewrite failed, passing through: {e!r}", flush=True)

        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def rewrite(self, data):
        uris = json.load(open(URIS_FILE))
        device = self.headers.get("ID", "?")
        st = load_state()
        dev = st.get(device, {})
        now = time.time()
        home_refresh = int(data.get("refresh_rate") or 300)
        last = dev.get("last")
        expected = int(dev.get("sent") or home_refresh)  # how long we told the device to sleep
        if last is not None and now - last < expected - EARLY_S:
            idx = (dev.get("idx", 0) + 1) % len(ROTATION)
            why = f"button ({now - last:.0f}s after last wake)"
        else:
            idx = 0
            why = "timer" if last is not None else "first request"
        name = ROTATION[idx]
        uri = uris.get(name)
        if not uri:
            st[device] = {"last": now, "idx": idx, "sent": home_refresh}
            save_state(st)
            return json.dumps(data)
        sent = home_refresh if idx == 0 else min(PAGE_REFRESH_S, home_refresh)
        data["refresh_rate"] = sent
        st[device] = {"last": now, "idx": idx, "sent": sent}
        save_state(st)
        base = urllib.parse.urlsplit(data["image_url"])
        data["image_url"] = f"{base.scheme}://{base.netloc}{uri}"
        data["filename"] = f"{name}-{os.path.splitext(os.path.basename(uri))[0]}"
        print(f"{device}: {why} -> {name}, next wake in {sent}s", flush=True)
        return json.dumps(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", CFG.get("port", 2302)), Handler).serve_forever()
