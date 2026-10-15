"""Minimal headless-Chrome CDP client for UI tests (stdlib only; DIRECTOR-OS-UX-03)."""
import base64, json, os, socket, struct, subprocess, tempfile, time, urllib.request
CH = os.environ.get("SPA_TEST_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


class Chrome:
    def __init__(self, port=None):
        if port is None:
            with socket.socket() as sk:
                sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]
        self.prof = tempfile.mkdtemp(prefix="claude_ux03_")
        self.p = subprocess.Popen([CH, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                                   f"--remote-debugging-port={port}", f"--user-data-dir={self.prof}",
                                   "--window-size=1280,900", "about:blank"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(80):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json")); break
            except Exception:
                time.sleep(0.2)
        ws = [t for t in tabs if t.get("type") == "page"][0]["webSocketDebuggerUrl"]
        host, rest = ws[5:].split("/", 1); h, pt = host.split(":")
        self.s = socket.create_connection((h, int(pt)))
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.send(f"GET /{rest} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                    f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        b = b""
        while b"\r\n\r\n" not in b:
            b += self.s.recv(4096)
        self.buf = b.split(b"\r\n\r\n", 1)[1]
        self.mid = 0
        self.call("Page.enable"); self.call("Runtime.enable")

    def _send(self, obj):
        data = json.dumps(obj).encode(); mask = os.urandom(4); n = len(data)
        hdr = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n)
                               if n < 65536 else bytes([0x80 | 127]) + struct.pack(">Q", n))
        self.s.send(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _recv(self):
        def need(k):
            while len(self.buf) < k:
                self.buf += self.s.recv(1 << 20)
        need(2); n = self.buf[1] & 0x7f; off = 2
        if n == 126: need(4); n = struct.unpack(">H", self.buf[2:4])[0]; off = 4
        elif n == 127: need(10); n = struct.unpack(">Q", self.buf[2:10])[0]; off = 10
        need(off + n); msg = self.buf[off:off + n]; self.buf = self.buf[off + n:]
        return json.loads(msg)

    def call(self, method, params=None):
        self.mid += 1; self._send({"id": self.mid, "method": method, "params": params or {}})
        while True:
            m = self._recv()
            if m.get("id") == self.mid:
                return m.get("result", m.get("error"))

    def ev(self, js):
        r = self.call("Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})
        return (r.get("result") or {}).get("value")

    def viewport(self, w, h=844, mobile=True):
        self.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 2 if mobile else 1,
                                                         "mobile": mobile})

    def go(self, url, wait=1.2):
        self.call("Page.navigate", {"url": url}); time.sleep(wait)

    def shot(self, path, full=False):
        params = {"format": "png"}
        if full:
            m = self.call("Page.getLayoutMetrics")
            cs = m["cssContentSize"]
            params.update({"captureBeyondViewport": True,
                           "clip": {"x": 0, "y": 0, "width": cs["width"], "height": min(cs["height"], 6000), "scale": 1}})
        r = self.call("Page.captureScreenshot", params)
        open(path, "wb").write(base64.b64decode(r["data"]))

    def key(self, k, shift=False):
        code = {"Tab": ("Tab", 9), "Enter": ("Enter", 13)}[k]
        mods = 8 if shift else 0
        for t in ("rawKeyDown", "keyUp"):
            self.call("Input.dispatchKeyEvent", {"type": t, "key": code[0], "code": code[0], "modifiers": mods,
                                                 "windowsVirtualKeyCode": code[1], "nativeVirtualKeyCode": code[1]})
        if k == "Enter":
            self.call("Input.dispatchKeyEvent", {"type": "char", "text": "\r", "modifiers": mods})

    def close(self):
        self.p.terminate(); time.sleep(0.3); subprocess.run(["rm", "-rf", self.prof])
