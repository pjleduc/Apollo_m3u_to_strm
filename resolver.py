#!/usr/bin/env python3
"""Local playback resolver for Apollo .strm files.

Apollo's tvnow.best is Cloudflare-fronted and blocks ffmpeg/curl by TLS
fingerprint (verified 2026-07-15: curl and ffmpeg get "connection reset by
peer" even with a browser User-Agent, while python-requests is allowed). It
issues short-lived signed redirects to a CDN host that ffmpeg CAN reach
directly.

This service resolves the signed URL per playback (using requests) and
302-redirects Jellyfin's ffmpeg to it. .strm files therefore contain a stable,
credential-free local URL:

    http://127.0.0.1:8770/s/<rest-of-apollo-path>

e.g. /s/movie/tt1618434  or  /s/tvshow/tt36629976/1/7

Credentials live only here (via APOLLO_USER / APOLLO_PASS in the environment),
not in the library files.
"""
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

USER = os.environ["APOLLO_USER"]
PASSWORD = os.environ["APOLLO_PASS"]
BASE = "https://tvnow.best/api/stream"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
PORT = int(os.environ.get("APOLLO_RESOLVER_PORT", "8770"))
REDIRECT_CODES = (301, 302, 303, 307, 308)


class Handler(BaseHTTPRequestHandler):
    def _resolve(self):
        if not self.path.startswith("/s/"):
            self.send_error(404)
            return
        rest = self.path[len("/s/"):]
        if not rest or ".." in rest:
            self.send_error(400)
            return
        upstream = f"{BASE}/{USER}/{PASSWORD}/{rest}"
        try:
            r = requests.get(
                upstream, headers={"User-Agent": UA},
                allow_redirects=False, timeout=(10, 30),
            )
        except requests.RequestException:
            self.send_error(502)
            return
        loc = r.headers.get("Location")
        if r.status_code in REDIRECT_CODES and loc:
            self.send_response(302)
            self.send_header("Location", loc)
            self.end_headers()
        else:
            self.send_error(502)

    def do_GET(self):
        self._resolve()

    def do_HEAD(self):
        self._resolve()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
