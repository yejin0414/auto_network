"""테스트용 가짜 SSH 장비(paramiko). 실제 netmiko 접속 경로를 검증합니다.

현장 장비에서 SecureCRT는 되는데 자동화 도구만 실패하는 대표 상황을 흉내 낼 수 있습니다.
- legacy=True: 오래된 Comware처럼 SHA-1 기반 방식(group14-sha1, ssh-rsa)만 제공
- kbd_only=True: 비밀번호(password) 인증 대신 keyboard-interactive만 허용
- login_question: 로그인 직후 프롬프트 전에 답을 요구하는 질문(예: 비밀번호 변경 [Y/N])
- motd: 프롬프트 전에 출력되는 긴 안내문(']' '>' 같은 문자 포함)
"""

from __future__ import annotations

import socket
import threading
from typing import Callable

import paramiko

HOST_KEY = paramiko.RSAKey.generate(2048)


class _Server(paramiko.ServerInterface):
    def __init__(self, user: str, pw: str, kbd_only: bool) -> None:
        self.user, self.pw, self.kbd_only = user, pw, kbd_only
        self.shell = threading.Event()

    def check_auth_password(self, username, password):
        if self.kbd_only:
            return paramiko.AUTH_FAILED
        return paramiko.AUTH_SUCCESSFUL if (username, password) == (self.user, self.pw) else paramiko.AUTH_FAILED

    def check_auth_interactive(self, username, submethods):
        if not self.kbd_only:
            return paramiko.AUTH_FAILED
        self._kbd_user = username
        q = paramiko.InteractiveQuery("", "")
        q.add_prompt("Password: ", False)
        return q

    def check_auth_interactive_response(self, responses):
        ok = getattr(self, "_kbd_user", None) == self.user and list(responses) == [self.pw]
        return paramiko.AUTH_SUCCESSFUL if ok else paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "keyboard-interactive" if self.kbd_only else "password"

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(self, *a):
        return True

    def check_channel_shell_request(self, channel):
        self.shell.set()
        return True


class MockDevice:
    """prompt: '<BB-3>' 또는 '(WLC-01) #'. responder(command) -> 출력."""

    def __init__(self, prompt: str, responder: Callable[[str], str], user="op", pw="pw", legacy: bool = False,
                 kbd_only: bool = False, login_question: str = "", motd: str = "") -> None:
        self.prompt, self.responder, self.user, self.pw = prompt, responder, user, pw
        self.legacy, self.kbd_only, self.login_question, self.motd = legacy, kbd_only, login_question, motd
        self.received: list[str] = []
        self.answers: list[str] = []
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(20)
        self.port = self.sock.getsockname()[1]
        self._stop = False
        threading.Thread(target=self._accept, daemon=True).start()

    def close(self) -> None:
        self._stop = True
        self.sock.close()

    def _accept(self) -> None:
        while not self._stop:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(c,), daemon=True).start()

    def _handle(self, c) -> None:
        t = paramiko.Transport(c)
        t.add_server_key(HOST_KEY)
        if self.legacy:
            t._preferred_kex = ("diffie-hellman-group14-sha1",)
            t._preferred_keys = ("ssh-rsa",)
            t._preferred_macs = ("hmac-sha1",)
        srv = _Server(self.user, self.pw, self.kbd_only)
        try:
            t.start_server(server=srv)
        except Exception:
            return
        ch = t.accept(10)
        if ch is None:
            return
        srv.shell.wait(5)
        buf = ""
        try:
            ch.send(("\r\n" + self.motd.replace("\n", "\r\n") + "\r\n").encode() if self.motd else b"\r\n")
            if self.login_question:
                ch.send(self.login_question.encode())
                answer = ""
                while True:
                    data = ch.recv(1024)
                    if not data:
                        return
                    answer += data.decode("utf-8", "replace")
                    if "\r" in answer or "\n" in answer or answer.strip()[:1].upper() in ("Y", "N"):
                        break
                self.answers.append(answer.strip())
                if answer.strip().upper().startswith("Y"):
                    ch.send(b"\r\nPlease input the old password:")
                    return  # 비밀번호 변경 단계로 넘어가면 자동화가 진행할 수 없음
                ch.send(b"\r\n")
            ch.send(self.prompt.encode())
            while True:
                data = ch.recv(4096)
                if not data:
                    break
                buf += data.decode("utf-8", "replace")
                while "\r" in buf or "\n" in buf:
                    idx = min(i for i in (buf.find("\r"), buf.find("\n")) if i >= 0)
                    line, buf = buf[:idx].strip(), buf[idx + 1:].lstrip("\n")
                    if line:
                        self.received.append(line)
                    if line in ("quit", "exit", "logout"):
                        ch.close()
                        return
                    out = self.responder(line) if line else ""
                    body = line + "\r\n" + (out.replace("\n", "\r\n") + "\r\n" if out else "")
                    ch.send((body + self.prompt).encode())
        except (OSError, EOFError):
            pass
        finally:
            t.close()
