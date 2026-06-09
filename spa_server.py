#!/usr/bin/env python3
import http.server, os, sys

os.chdir('/Users/yuriikulieshov/Documents/SPA_Claude')

class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stderr.write("[spa-server] %s\n" % (format % args))

httpd = http.server.HTTPServer(('', 8765), Handler)
print("[spa-server] Serving on http://localhost:8765", flush=True)
httpd.serve_forever()
