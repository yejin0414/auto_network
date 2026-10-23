"""Bound diagnostic response reads using synthetic sockets and virtual clocks.

No real connection or sleep occurs. Existing EOF/algorithm-format regressions
remain in test_collection_regressions.py; these cases target the missing limits.
"""
from __future__ import annotations

import struct
import unittest
from unittest.mock import Mock, patch

import nc.diagnose as D


BANNER = b"SSH-2.0-Synthetic_1.0\r\n"
IDENTIFICATION = b"SSH-2.0-NetcheckProbe_1.0\r\n"
ALGORITHMS = (
    b"curve25519-sha256,diffie-hellman-group14-sha256",
    b"ssh-ed25519,rsa-sha2-256", b"aes128-ctr", b"aes256-ctr", b"hmac-sha2-256", b"",
)
PAYLOAD = b"\x14" + b"\x00" * 16 + b"".join(struct.pack(">I", len(a)) + a for a in ALGORITHMS)
EXPECTED_LISTS = {key: value.decode("ascii").split(",") if value else []
                  for key, value in zip(D.KEXINIT_NAMES, ALGORITHMS)}


def packet(payload=PAYLOAD):
    return struct.pack(">I", len(payload) + 5) + b"\x04" + payload + b"\x00" * 4


def fragments(data, size=4096):
    return [data[start:start + size] for start in range(0, len(data), size)]


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Socket:
    def __init__(self, chunks, *, delays=(), honor_timeout=True, settimeout_error=None, send_delay=0):
        self.clock = Clock()
        self.chunks = list(chunks)
        self.delays = iter(delays)
        self.honor_timeout = honor_timeout
        self.settimeout_error = settimeout_error
        self.send_delay = send_delay
        self.timeouts = []
        self.sent = []
        self.recv_calls = 0
        self.received_bytes = 0
        self.close_calls = 0
        self.connections = []

    def settimeout(self, seconds):
        self.timeouts.append(seconds)
        if self.settimeout_error:
            raise self.settimeout_error
        self.timeout = seconds

    def sendall(self, data):
        self.sent.append(data)
        self.clock.advance(self.send_delay)

    def recv(self, size):
        self.recv_calls += 1
        delay = next(self.delays, 0.0)
        if self.honor_timeout and delay > self.timeout:
            self.clock.advance(self.timeout)
            raise TimeoutError("synthetic socket timeout")
        self.clock.advance(delay)
        chunk = self.chunks.pop(0) if self.chunks else b""
        if len(chunk) > size:
            raise AssertionError("socket fixture exceeded the requested recv size")
        self.received_bytes += len(chunk)
        return chunk

    def close(self):
        self.close_calls += 1


class DiagnosticReadLimits(unittest.TestCase):
    def probe(self, sock, timeout=1.0, *, connect_delay=0.0):
        def connect(address, timeout):
            sock.connections.append((address, timeout))
            sock.clock.advance(connect_delay)
            return sock

        with patch("nc.diagnose.socket.create_connection", side_effect=connect), \
                patch("nc.diagnose.time.monotonic", side_effect=sock.clock.monotonic):
            return D.read_server_kexinit("synthetic.invalid", 22, timeout)

    def assert_normal(self, result, pre):
        self.assertEqual(result, (BANNER.rstrip(b"\r\n").decode("ascii"), pre, EXPECTED_LISTS))

    def test_completed_preamble_lines_and_empty_lines_share_the_byte_limit(self):
        cases = (
            [b"x" * 1023 + b"\n"] * 80,
            [b"\n" * 4096] * 20,
            [("é" * 511).encode("utf-8") + b"\r\n"] * 80,
        )
        for preamble in cases:
            with self.subTest(chunk=preamble[0][:12]):
                sock = Socket(preamble + [BANNER + packet()])
                with self.assertRaisesRegex(ConnectionError, "SSH 배너가 아닌 데이터가 너무 깁니다"):
                    self.probe(sock)
                self.assertLess(sock.recv_calls, len(preamble) + 1)
                self.assertLessEqual(sock.received_bytes, 65536 + 4096)
                self.assertEqual(sock.close_calls, 1)

    def test_banner_header_and_body_share_one_response_deadline(self):
        body = packet()
        chunks = [b"notice\n", BANNER, body[:2], body[2:5], body[5:20], body[20:]]
        sock = Socket(chunks, delays=[0.3] * len(chunks))
        with self.assertRaises(TimeoutError):
            self.probe(sock)
        self.assertLessEqual(sock.clock.now, 1.0 + 1e-9)
        self.assertLess(sock.recv_calls, len(chunks))
        self.assertTrue(any(0 < value < 1.0 for value in sock.timeouts))
        self.assertEqual(sock.close_calls, 1)

    def test_successful_final_recv_after_deadline_is_not_accepted(self):
        # Even a recv returning data may be observed after its deadline, e.g.
        # after the caller was descheduled. Check the completed response too.
        sock = Socket([BANNER, packet()], delays=[0.6, 0.6], honor_timeout=False)
        with self.assertRaises(TimeoutError):
            self.probe(sock)
        self.assertEqual(sock.recv_calls, 2)
        self.assertAlmostEqual(sock.clock.now, 1.2)
        self.assertEqual(sock.close_calls, 1)

    def test_initial_settimeout_failure_closes_the_acquired_socket(self):
        error = OSError("synthetic settimeout failure")
        sock = Socket([], settimeout_error=error)
        with self.assertRaises(OSError) as caught:
            self.probe(sock)
        self.assertIs(caught.exception, error)
        self.assertEqual(sock.sent, [])
        self.assertEqual(sock.recv_calls, 0)
        self.assertEqual(sock.close_calls, 1)

    def test_fragmented_preamble_banner_and_kex_keep_existing_values(self):
        preamble = "notice café\r\n".encode("utf-8") + b"\r\ninvalid \xff\n"
        sock = Socket(fragments(preamble + BANNER + packet(), size=1))
        self.assert_normal(self.probe(sock), ["notice café", "", "invalid �"])
        self.assertEqual(sock.sent, [IDENTIFICATION])
        self.assertEqual(sock.connections, [(("synthetic.invalid", 22), 1.0)])
        self.assertEqual(sock.close_calls, 1)

    def test_banner_phase_accepts_exact_limit_and_rejects_one_extra_byte(self):
        for extra in (0, 1):
            with self.subTest(extra=extra):
                line = b"x" * (65536 - len(BANNER) - 1 + extra)
                wire = line + b"\n" + BANNER + packet()
                sock = Socket(fragments(wire))
                if extra:
                    with self.assertRaisesRegex(ConnectionError, "SSH 배너가 아닌 데이터가 너무 깁니다"):
                        self.probe(sock)
                else:
                    self.assert_normal(self.probe(sock), [line.decode("ascii")])
                self.assertEqual(sock.close_calls, 1)

    def test_coalesced_banner_and_maximum_kex_keep_independent_length_limits(self):
        # plen excludes the four length bytes, so the largest accepted frame is
        # 65,540 wire bytes. Trailing payload bytes retain the existing parser's
        # handling after its six reported algorithm lists.
        largest = packet(PAYLOAD + b"\x00" * (65531 - len(PAYLOAD)))
        self.assertEqual(int.from_bytes(largest[:4], "big"), 65536)
        self.assertEqual(len(largest), 65540)
        preamble = (b"p" * 999 + b"\n") * 64
        sock = Socket(fragments(preamble + BANNER + largest))
        self.assert_normal(self.probe(sock), ["p" * 999] * 64)
        self.assertGreater(sock.received_bytes, 2 * 65536 - 4096)
        self.assertEqual(sock.close_calls, 1)
        # The neighboring packet-length rejection remains unchanged.
        invalid = Socket([BANNER + struct.pack(">I", 65537) + b"\x04"])
        with self.assertRaisesRegex(ConnectionError, "KEXINIT 길이가 비정상입니다"):
            self.probe(invalid)
        self.assertEqual(invalid.close_calls, 1)

    def test_connect_and_send_keep_their_existing_separate_timeout_allowances(self):
        sock = Socket([BANNER, packet()], delays=[0.2, 0.2], send_delay=0.05)
        self.assert_normal(self.probe(sock, connect_delay=0.8), [])
        self.assertAlmostEqual(sock.clock.now, 1.25)
        self.assertEqual(sock.connections[0][1], 1.0)
        self.assertEqual(sock.timeouts[0], 1.0)
        self.assertEqual(sock.sent, [IDENTIFICATION])
        self.assertEqual(sock.close_calls, 1)

    def test_login_screen_read_keeps_six_and_four_second_budgets_across_clock_jumps(self):
        for seconds in (6, 4):
            for jump in (-1000000, 1000000):
                with self.subTest(seconds=seconds, jump=jump):
                    clock = Clock()
                    channel = Mock()
                    available = [True]
                    channel.recv_ready.side_effect = lambda: available.pop() if available else False
                    channel.recv.return_value = b"synthetic login screen\r\n"
                    wall_calls = [0]

                    def wall_time():
                        wall_calls[0] += 1
                        return clock.now + (jump if wall_calls[0] > 1 else 0)

                    def sleep(delay):
                        clock.advance(delay)
                        if clock.now > seconds + 1:
                            raise AssertionError("wall-clock jump extended the synthetic screen read")

                    with patch("nc.diagnose.time.monotonic", side_effect=clock.monotonic), \
                            patch("nc.diagnose.time.time", side_effect=wall_time), \
                            patch("nc.diagnose.time.sleep", side_effect=sleep):
                        self.assertEqual(D._read(channel, seconds), "synthetic login screen\r\n")
                    self.assertGreaterEqual(clock.now, seconds)
                    self.assertLess(clock.now, seconds + 0.201)
                    channel.recv.assert_called_once_with(65535)


if __name__ == "__main__":
    unittest.main()
