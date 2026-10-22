"""테스트용 가짜 Telnet Comware 장비."""
from __future__ import annotations

import socket
import threading
from typing import Callable

IAC = 255


def _strip_iac(data: bytes) -> bytes:
    out, i = bytearray(), 0
    while i < len(data):
        b = data[i]
        if b == IAC and i + 1 < len(data):
            cmd = data[i + 1]
            if cmd in (251, 252, 253, 254):  # WILL WONT DO DONT + 옵션
                i += 3
                continue
            if cmd == 250:  # SB ... SE
                end = data.find(bytes([IAC, 240]), i)
                i = end + 2 if end >= 0 else len(data)
                continue
            i += 2
            continue
        out.append(b)
        i += 1
    return bytes(out)


class MockTelnetDevice:
    def __init__(self, prompt: str, responder: Callable[[str], str], user="op", pw="pw") -> None:
        self.prompt, self.responder, self.user, self.pw = prompt, responder, user, pw
        self.received: list[str] = []
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(10)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def close(self) -> None:
        self.sock.close()

    def _accept(self) -> None:
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(c,), daemon=True).start()

    def _lines(self, c):
        buf = b""
        while True:
            data = c.recv(4096)
            if not data:
                return
            buf += _strip_iac(data).replace(b"\x00", b"")
            while b"\r" in buf or b"\n" in buf:
                idx = min(i for i in (buf.find(b"\r"), buf.find(b"\n")) if i >= 0)
                line, buf = buf[:idx], buf[idx + 1:].lstrip(b"\n")
                yield line.decode("utf-8", "replace").strip()

    def _handle(self, c) -> None:
        try:
            c.sendall(b"\r\n******************************\r\n* Copyright (c) HPE.          *\r\n******************************\r\n\r\nLogin authentication\r\n\r\n\r\nUsername:")
            lines = self._lines(c)
            user = next(lines)
            while not user:
                user = next(lines)
            c.sendall(b"Password:")
            pw = next(lines)
            if (user, pw) != (self.user, self.pw):
                c.sendall(b"\r\n% Authentication failed.\r\n")
                c.close()
                return
            c.sendall(("\r\n" + self.prompt).encode())
            for line in lines:
                if line:
                    self.received.append(line)
                if line in ("quit", "exit", "logout"):
                    break
                out = self.responder(line) if line else ""
                body = line + "\r\n" + (out.replace("\n", "\r\n") + "\r\n" if out else "")
                c.sendall((body + self.prompt).encode())
        except (OSError, StopIteration):
            pass
        finally:
            c.close()
