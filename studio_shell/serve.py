#!/usr/bin/env python3
"""Studio OS Shell — local read-only static server. Loopback ONLY (deployment rule #8).

Serves studio_shell/ over http://127.0.0.1:<port>. Rebuilds the read model on start (and
on each GET of /read_model.json if --live) so the UI reflects current canonical state.
Read-only: serves files, never writes canon, no secrets. stdlib only (invariant #4).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / 'build_read_model.py'


def rebuild():
    try:
        subprocess.run([sys.executable, str(BUILD)], check=True, capture_output=True,
                       text=True, timeout=60)
    except (subprocess.SubprocessError, OSError) as exc:
        print(f'[serve] read-model rebuild failed: {exc}', file=sys.stderr)


class Handler(SimpleHTTPRequestHandler):
    live = False

    def do_GET(self):
        if self.live and self.path.split('?')[0].endswith('/read_model.json'):
            rebuild()
        return super().do_GET()

    def log_message(self, format, *args):  # quieter
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port', type=int, default=8777)
    ap.add_argument('--live', action='store_true',
                    help='rebuild read_model.json on each fetch (default: once at start)')
    ns = ap.parse_args(argv)
    rebuild()
    Handler.live = ns.live
    handler = partial(Handler, directory=str(HERE))
    # 127.0.0.1 ONLY — never all interfaces (deployment rule #8).
    httpd = ThreadingHTTPServer(('127.0.0.1', ns.port), handler)
    print(f'Studio OS Shell → http://127.0.0.1:{ns.port}/  (loopback only, read-only, '
          f'live={ns.live})')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == '__main__':
    main()
