#!/usr/bin/env python3
"""End-to-end check of the browser host without a browser: fetches the page, opens the WebSocket (checking the
RFC 6455 accept key), assembles the frame rectangles into a full 1024x640 frame, sends input, and checks the frame
reacts. Writes the assembled frames as PNGs when Pillow is there.

Usage: test_client.py [PORT] [OUT_DIR]   (the host must be running: ./out/browser PORT)
"""
import base64, hashlib, os, socket, struct, sys, time

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
OUT = sys.argv[2] if len(sys.argv) > 2 else "."
W, H = 1024, 640


def http_get(path):
    s = socket.create_connection(("127.0.0.1", PORT))
    s.sendall(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    data = b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    head, _, body = data.partition(b"\r\n\r\n")
    return head.decode(), body


class Ws:
    def __init__(self):
        self.s = socket.create_connection(("127.0.0.1", PORT))
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            head += self.s.recv(1)
        want = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        assert b"101" in head.split(b"\r\n")[0], head
        assert f"Sec-WebSocket-Accept: {want}".encode() in head, (head, want)
        self.buf = b""
        self.frame = bytearray(W * H * 4)
        self.cursor = None

    def send(self, text):
        payload = text.encode()
        mask = os.urandom(4)
        header = bytes([0x81, 0x80 | len(payload)]) + mask
        self.s.sendall(header + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(1 << 20)
            if not chunk:
                raise EOFError
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def message(self):
        b0, b1 = self._read(2)
        n = b1 & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._read(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._read(8))[0]
        return b0 & 0x0F, self._read(n)

    def pump(self, seconds):
        """Applies every message for `seconds`; returns how many rectangles came."""
        self.s.settimeout(0.05)
        end = time.time() + seconds
        rects = 0
        while time.time() < end:
            try:
                op, data = self.message()
            except socket.timeout:
                continue
            if op == 1:
                self.cursor = data.decode().split()[1]
            elif op == 2:
                x, y, w, h = struct.unpack("<HHHH", data[:8])
                for row in range(h):
                    start = ((y + row) * W + x) * 4
                    self.frame[start:start + w * 4] = data[8 + row * w * 4:8 + (row + 1) * w * 4]
                rects += 1
        return rects

    def pixel(self, x, y):
        i = (y * W + x) * 4
        return tuple(self.frame[i:i + 3])

    def save(self, name):
        try:
            from PIL import Image
        except ImportError:
            return
        Image.frombytes("RGBA", (W, H), bytes(self.frame)).convert("RGB").save(os.path.join(OUT, name))


def main():
    head, body = http_get("/")
    assert head.startswith("HTTP/1.1 200") and b"<canvas" in body, head
    assert http_get("/nope")[0].startswith("HTTP/1.1 404")
    ws = Ws()
    first = ws.pump(0.6)
    assert first >= 1, "no frame arrived"
    ws.save("browser-0-initial.png")
    idle = ws.pump(0.5)
    # The page is animated (the PRO badge rocks, the uptime counts), so frames keep coming, but only small rectangles.
    print(f"initial: {first} rectangle(s); idle 0.5s: {idle}")
    # Hover the counter button: the cursor becomes a pointer.
    ws.send("m 855 46")
    ws.pump(0.3)
    assert ws.cursor == "pointer", ws.cursor
    # Click it twice: the label reads "Clicked 2".
    for _ in range(2):
        ws.send("d 855 46 0")
        ws.pump(0.1)
        ws.send("u 855 46 0")
        ws.pump(0.1)
    ws.pump(0.4)
    ws.save("browser-1-clicked.png")
    # Open the Controls tab and type into the name field.
    ws.send("m 100 124")
    ws.pump(0.1)
    ws.send("d 100 124 0")
    ws.pump(0.1)
    ws.send("u 100 124 0")
    ws.pump(0.3)
    ws.send("m 480 170")
    ws.pump(0.1)
    ws.send("d 480 170 0")
    ws.pump(0.1)
    ws.send("u 480 170 0")
    ws.pump(0.1)
    for ch in "CeeSafe":
        ws.send(f"c {ord(ch)}")
        ws.pump(0.03)
    ws.send("k Tab")
    ws.send("K Tab")
    ws.pump(0.5)
    ws.save("browser-2-typed.png")
    # Enter leaves the field; then T (no field focused) switches to light mode: the background turns light.
    ws.send("k Enter")
    ws.send("K Enter")
    ws.pump(0.1)
    ws.send("c 84")
    ws.pump(0.4)
    bg = ws.pixel(1000, 630)
    ws.save("browser-3-light.png")
    print("light-mode background", bg)
    assert sum(bg) > 600, bg
    ws.s.close()
    print("ok")


if __name__ == "__main__":
    main()
