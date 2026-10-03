#!/usr/bin/env python3
"""
dns_simulator.py
================
Local DNS simulator for the multi-tenant SaaS sandbox.

Why this exists
---------------
The whole multi-tenant architecture identifies a business by its hostname:
``acme.local-saas.com`` serves Acme's storefront, ``nike.local-saas.com``
serves Nike's. Those hostnames do not exist in the public DNS, so the
developer machine needs its own resolver that:

1. answers EVERY name inside the sandbox zone (``*.local-saas.com``) with
   ``127.0.0.1`` (a wildcard A record), and
2. forwards EVERY other query verbatim to a real public resolver
   (``8.8.8.8``) so the machine keeps working normally while this server
   is configured as the system resolver.

Both UDP (standard queries) and TCP (large / truncated responses) are
served. Non-A/AAAA queries for names inside the zone return a NOERROR
empty answer (NODATA) instead of falling through to the upstream, which
would leak private hostnames to the public resolver.

Usage
-----
    pip install dnslib

    # Windows: run the terminal *as Administrator* (UDP/TCP port 53)
    python dns_simulator.py

    # non-privileged port, for manual dig/nslookup checks only
    # (avoid 5353 = mDNS and 5355 = LLMNR: Windows services own those)
    python dns_simulator.py --port 5454

    # start the server, run sanity checks against it, then exit
    python dns_simulator.py --self-test --port 53

Point the OS resolver at it
---------------------------
Windows (elevated shell; "Wi-Fi" is your adapter name - check with
``netsh interface show interface``)::

    netsh interface ip set   dns name="Wi-Fi" static 127.0.0.1
    netsh interface ip add   dns name="Wi-Fi" 8.8.8.8 index=2   # fallback
    ipconfig /flushdns

    # revert to DHCP
    netsh interface ip set dns name="Wi-Fi" source=dhcp

Linux: prepend ``nameserver 127.0.0.1`` to ``/etc/resolv.conf`` (or set it
in NetworkManager / systemd-resolved for the active connection).

Manual check::

    nslookup acme.local-saas.com 127.0.0.1    # -> 127.0.0.1
    nslookup example.com 127.0.0.1            # -> real public IP (proxied)

Operational notes
-----------------
* Windows caches DNS aggressively: run ``ipconfig /flushdns`` whenever a
  new tenant subdomain is added or ``--local-ip`` changes.
* TTL is deliberately low (30s) so stale cache never outlives a restart.
* The OS fallback entry (8.8.8.8) keeps the machine online if this
  process is stopped, because everything except the sandbox zone is
  proxied anyway.
* Starting Django/Frontend on port 80 also needs admin rights; an easier
  dev loop is ``http://acme.local-saas.com:8000`` / ``:5173``.
"""

from __future__ import annotations

import argparse
import logging
import socket
import socketserver
import struct
import sys
import threading
import time
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from dnslib import A, DNSRecord, QTYPE, RR, RCODE
    from dnslib.server import DNSLogger, DNSServer, TCPServer, UDPServer
except ImportError:  # pragma: no cover - environment guard
    sys.stderr.write("[!] dnslib is not installed -> run: pip install dnslib\n")
    raise SystemExit(1)


LOGGER = logging.getLogger("dns_simulator")

# dnslib's own per-query console logging; silenced so *our* decision log
# (LOCAL / PROXY / FAIL) stays the single source of truth.
DNSLIB_LOGGER = DNSLogger(log="-request,-reply,-truncated,-error")


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #
class Stats:
    """Thread-safe request counters (one thread per client connection)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: Dict[str, int] = {"local": 0, "proxy": 0, "failed": 0}
        self._started = time.time()

    def bump(self, kind: str) -> None:
        with self._lock:
            self._counts[kind] = self._counts.get(kind, 0) + 1

    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            out = dict(self._counts)
        out["uptime"] = int(time.time() - self._started)
        return out


# --------------------------------------------------------------------------- #
# Resolver: local wildcard zone + upstream forwarder
# --------------------------------------------------------------------------- #
class MultiTenantResolver:
    """
    dnslib resolver hooking into ``DNSServer``.

    Decision tree for a query ``Q`` of type ``T`` for name ``N``:

    ``N`` inside sandbox zone?
        yes, T in (A, ANY)  -> answer 127.0.0.1 (wildcard, authoritative)
        yes, T otherwise    -> NOERROR / 0 answers (NODATA: the name exists,
                               but has no MX/TXT/AAAA ... record)
        no                  -> raw bytes forwarded to upstream over UDP,
                               transparently retried over TCP if the reply
                               carries the Truncated (TC) bit
    """

    def __init__(self, args: argparse.Namespace) -> None:
        self.zone: str = args.zone
        self.local_ip: str = args.local_ip
        self.include_apex: bool = args.include_apex
        self.upstream: str = args.upstream
        self.upstream_port: int = args.upstream_port
        self.timeout: float = args.timeout
        self.ttl: int = args.ttl
        self.stats = Stats()

    # -- zone matching ----------------------------------------------------- #
    def is_local(self, qname: str) -> bool:
        name = qname.lower().rstrip(".")
        if name == self.zone:
            return self.include_apex
        return name.endswith("." + self.zone)

    # -- public entry point called by dnslib -------------------------------- #
    def resolve(self, request: DNSRecord, handler) -> DNSRecord:
        started = time.perf_counter()
        qname = str(request.q.qname)
        qtype = QTYPE[request.q.qtype]
        client = self._client(handler)

        if self.is_local(qname):
            reply = self._answer_local(request)
            self.stats.bump("local")
            # Be honest in the log: a AAAA/MX/TXT query for a known tenant
            # hostname is answered with NODATA (0 answers), not with local_ip.
            answers = ", ".join(str(rr.rdata) for rr in reply.rr) \
                or "NODATA (no %s record)" % qtype
            LOGGER.info(
                "LOCAL  %-6s %-42s -> %-24s (%5.1f ms) client=%s",
                qtype, qname, answers, self._ms(started), client,
            )
            return reply

        # dnslib 0.9.x has no DNSRecord.__bytes__ -> use .pack()
        raw = self._forward(request.pack())
        if raw is None:
            self.stats.bump("failed")
            LOGGER.error(
                "FAIL   %-6s %-42s upstream %s:%s unreachable (%5.1f ms)",
                qtype, qname, self.upstream, self.upstream_port, self._ms(started),
            )
            return self._error_reply(request, RCODE.SERVFAIL)

        try:
            reply = DNSRecord.parse(raw)
        except Exception as exc:  # malformed upstream payload
            self.stats.bump("failed")
            LOGGER.error("FAIL   %-6s %-42s malformed upstream reply: %s", qtype, qname, exc)
            return self._error_reply(request, RCODE.SERVFAIL)

        self.stats.bump("proxy")
        answers = ", ".join(str(rr.rdata) for rr in reply.rr) or "-"
        LOGGER.info(
            "PROXY  %-6s %-42s -> %s [%s] (%5.1f ms)",
            qtype, qname, answers, self.upstream, self._ms(started),
        )
        return reply

    # -- local answers ------------------------------------------------------ #
    def _answer_local(self, request: DNSRecord) -> DNSRecord:
        reply = request.reply()  # QR=1, echoes question, AA=1
        if request.q.qtype in (QTYPE.A, QTYPE.ANY):
            reply.add_answer(
                RR(request.q.qname, QTYPE.A, rdata=A(self.local_ip), ttl=self.ttl)
            )
        # AAAA/MX/TXT/... intentionally left as NOERROR/NODATA: the hostname
        # exists (wildcard), it simply has no such record. Resolvers then
        # continue with the A query instead of failing the whole lookup.
        return reply

    @staticmethod
    def _error_reply(request: DNSRecord, rcode) -> DNSRecord:
        reply = request.reply()
        reply.header.rcode = rcode
        return reply

    # -- upstream forwarding ------------------------------------------------ #
    def _forward(self, payload: bytes) -> Optional[bytes]:
        """Forward raw request bytes; return raw response bytes (or None)."""
        data = self._forward_udp(payload)
        if data is None:
            return None
        if self._truncated(data):
            LOGGER.debug("TC bit set - retrying over TCP")
            tcp_data = self._forward_tcp(payload)
            if tcp_data is not None:
                return tcp_data
            # TCP failed (blocked port 53/tcp): better to return the partial
            # truncated answer than nothing at all.
        return data

    def _forward_udp(self, payload: bytes) -> Optional[bytes]:
        expected_id = struct.unpack("!H", payload[:2])[0]
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(self.timeout)
                sock.sendto(payload, (self.upstream, self.upstream_port))
                for _ in range(3):  # discard stray/mismatched datagrams
                    data, _addr = sock.recvfrom(65535)
                    if len(data) < 12:
                        continue
                    if struct.unpack("!H", data[:2])[0] != expected_id:
                        LOGGER.debug("dropping upstream reply with mismatched ID")
                        continue
                    return data
        except OSError as exc:
            LOGGER.warning("upstream UDP %s:%s error: %s",
                           self.upstream, self.upstream_port, exc)
        return None

    def _forward_tcp(self, payload: bytes) -> Optional[bytes]:
        expected_id = struct.unpack("!H", payload[:2])[0]
        try:
            with socket.create_connection(
                (self.upstream, self.upstream_port), timeout=self.timeout
            ) as sock:
                sock.settimeout(self.timeout)
                sock.sendall(struct.pack("!H", len(payload)) + payload)
                header = self._recv_exact(sock, 2)
                if not header:
                    return None
                length = struct.unpack("!H", header)[0]
                data = self._recv_exact(sock, length)
                if data and struct.unpack("!H", data[:2])[0] == expected_id:
                    return data
        except OSError as exc:
            LOGGER.warning("upstream TCP %s:%s error: %s",
                           self.upstream, self.upstream_port, exc)
        return None

    @staticmethod
    def _recv_exact(sock: socket.socket, size: int) -> Optional[bytes]:
        chunks: List[bytes] = []
        remaining = size
        while remaining > 0:
            chunk = sock.recv(remaining)
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    @staticmethod
    def _truncated(data: bytes) -> bool:
        # DNS header: ID(2) | flags(2); TC is bit 1 of the flags word.
        return len(data) >= 4 and bool(data[2] & 0x02)

    # -- misc --------------------------------------------------------------- #
    @staticmethod
    def _client(handler) -> str:
        client = getattr(handler, "client", None) or getattr(handler, "client_address", None)
        return client[0] if client else "unknown"

    @staticmethod
    def _ms(started: float) -> float:
        return (time.perf_counter() - started) * 1000


# --------------------------------------------------------------------------- #
# Server bootstrap / teardown
# --------------------------------------------------------------------------- #
class StrictUDPServer(UDPServer):
    """
    dnslib's server classes force ``allow_reuse_address = True``. On Windows
    that lets a *second* process bind the exact same (host, port) and
    silently split the traffic: a stale simulator would keep answering with
    outdated ``--zone``/``--local-ip`` settings while the new one looks
    "running" (its own counters stay at 0).

    Binding strictly makes a duplicate start fail with EADDRINUSE instead.
    We skip dnslib's ``__init__`` (that is where the reuse flag is forced on)
    and keep the rest of its behaviour - notably ``get_request()`` which hands
    the UDP socket to the handler so replies can be sent.
    """

    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, server_address, handler) -> None:
        if server_address[0] and ":" in server_address[0]:
            self.address_family = socket.AF_INET6
        socketserver.UDPServer.__init__(self, server_address, handler)


class StrictTCPServer(TCPServer):
    """TCP twin of :class:`StrictUDPServer` (same strict bind semantics)."""

    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, server_address, handler) -> None:
        if server_address[0] and ":" in server_address[0]:
            self.address_family = socket.AF_INET6
        socketserver.TCPServer.__init__(self, server_address, handler)


def _bind_failure(exc: OSError, args: argparse.Namespace) -> SystemExit:
    """Turn a raw socket error into an actionable message."""
    code = getattr(exc, "errno", None)
    if code in (13, 10013):  # EACCES / WSAEACCES
        lines = ["[!] Access denied while binding port %d. Likely causes:" % args.port]
        if args.port < 1024:
            lines.append("    - privileged port (< 1024) -> needs root/Administrator")
        lines += [
            "    - Windows: the port sits in an excluded port range, or another service",
            "      owns it exclusively (classic offenders: UDP 5353 = mDNS, 5355 = LLMNR)",
            "    Windows : netsh interface ipv4 show excludedportrange protocol=udp",
            "              netstat -ano | findstr :%d" % args.port,
            "    Linux   : sudo python dns_simulator.py   (only needed for port 53)",
            "    ...or simply choose a free port with --port",
        ]
        hint = "\n" + "\n".join(lines)
    elif code in (98, 10048):  # EADDRINUSE / WSAEADDRINUSE
        hint = ("\n[!] Port %d is already in use.\n"
                "    Another dns_simulator.py instance is probably still running.\n"
                "    Windows : netstat -ano | findstr :%d\n"
                "    Linux   : sudo lsof -iUDP:%d -iTCP:%d"
                % (args.port, args.port, args.port, args.port))
    return SystemExit("[!] Cannot bind %s:%d - %s%s" % (args.host, args.port, exc, hint))


def start_servers(resolver: MultiTenantResolver, args: argparse.Namespace) -> List[Tuple[str, DNSServer]]:
    """
    Bind + start the UDP (and TCP) listeners.

    dnslib specifics: the socket is bound inside ``DNSServer.__init__`` and
    the accept loop is launched with ``start_thread()`` (``start()`` blocks).
    A server must therefore only be registered for shutdown *after* its
    thread is running - ``DNSServer.stop()`` -> ``socketserver.shutdown()``
    blocks forever if ``serve_forever()`` was never started.
    """
    servers: List[Tuple[str, DNSServer]] = []
    try:
        udp = DNSServer(resolver, address=args.host, port=args.port,
                        tcp=False, logger=DNSLIB_LOGGER, server=StrictUDPServer)
    except OSError as exc:
        raise _bind_failure(exc, args)
    udp.start_thread()
    servers.append(("UDP", udp))

    if not args.no_tcp:
        try:
            tcp = DNSServer(resolver, address=args.host, port=args.port,
                            tcp=True, logger=DNSLIB_LOGGER, server=StrictTCPServer)
        except OSError as exc:
            # TCP is a nice-to-have (large responses); UDP alone still works.
            LOGGER.warning("TCP listener unavailable (%s) - continuing UDP only", exc)
        else:
            tcp.start_thread()
            servers.append(("TCP", tcp))
    return servers


def stop_servers(servers: Sequence[Tuple[str, DNSServer]]) -> None:
    for _kind, srv in servers:
        try:
            srv.stop()
        except Exception:  # pragma: no cover - best effort shutdown
            pass


def print_banner(args: argparse.Namespace) -> None:
    transports = "UDP+TCP" if not args.no_tcp else "UDP"
    apex = args.zone if args.include_apex else "*.%s" % args.zone
    print("=" * 74)
    print(" Local DNS simulator - multi-tenant sandbox resolver")
    print("=" * 74)
    print(" listen    : %-21s %s:%d" % (transports, args.host, args.port))
    print(" zone      : %-21s -> %s" % (apex, args.local_ip))
    print(" upstream  : %-21s (all other queries)" % "%s:%d" % (args.upstream, args.upstream_port))
    print("-" * 74)
    print(" Point the OS at this resolver, then flush the cache:")
    print("   Windows : netsh interface ip set dns name=\"<adapter>\" static %s" % args.host)
    print("             netsh interface ip add dns name=\"<adapter>\" 8.8.8.8 index=2")
    print("             ipconfig /flushdns")
    print("   Linux   : echo 'nameserver %s' | sudo tee /etc/resolv.conf" % args.host)
    print(" check     : nslookup acme.%s %s" % (args.zone, args.host))
    print("             nslookup example.com %s" % args.host)
    print(" stop      : Ctrl+C")
    print("=" * 74)


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #
def query(server: str, port: int, name: str, qtype: str = "A",
          timeout: float = 3.0) -> DNSRecord:
    request = DNSRecord.question(name, qtype)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(request.pack(), (server, port))
        data, _ = sock.recvfrom(65535)
    return DNSRecord.parse(data)


def run_self_test(args: argparse.Namespace) -> int:
    """
    Start the server on the requested port, exercise both code paths
    (local wildcard + upstream proxy) and report PASS/WARN/FAIL lines.
    Returns a process exit code.
    """
    resolver = MultiTenantResolver(args)
    servers = start_servers(resolver, args)
    failures = 0
    time.sleep(0.3)  # let the threads accept
    try:
        checks: List[Tuple[str, str, str]] = []  # (label, status, detail)

        # 1. wildcard tenant subdomain
        sub = "acme.%s" % args.zone
        try:
            reply = query(args.host, args.port, sub, timeout=args.timeout)
            got = ", ".join(str(rr.rdata) for rr in reply.rr) or "<no answer>"
            ok = reply.header.rcode == RCODE.NOERROR and got == args.local_ip
        except Exception as exc:
            ok, got = False, "exception: %s" % exc
        checks.append(("wildcard A  %s" % sub, "PASS" if ok else "FAIL", got))

        # 2. deeper tenant label (a.b.zone) still matches the wildcard
        deep = "shop.eu.%s" % args.zone
        try:
            reply = query(args.host, args.port, deep, timeout=args.timeout)
            got = ", ".join(str(rr.rdata) for rr in reply.rr) or "<no answer>"
            ok = got == args.local_ip
        except Exception as exc:
            ok, got = False, "exception: %s" % exc
        checks.append(("wildcard A  %s" % deep, "PASS" if ok else "FAIL", got))

        # 3. non-existent record type inside the zone -> NODATA, not upstream
        try:
            reply = query(args.host, args.port, sub, "AAAA", timeout=args.timeout)
            ok = reply.header.rcode == RCODE.NOERROR and len(reply.rr) == 0
            got = "rcode=%s answers=%d" % (RCODE[reply.header.rcode], len(reply.rr))
        except Exception as exc:
            ok, got = False, "exception: %s" % exc
        checks.append(("NODATA      %s AAAA" % sub, "PASS" if ok else "FAIL", got))

        # 4. outside the zone -> forwarded to the public resolver
        try:
            reply = query(args.host, args.port, "example.com", timeout=args.timeout)
            got = ", ".join(str(rr.rdata) for rr in reply.rr) or "<no answer>"
            if reply.header.rcode == RCODE.NOERROR and reply.rr:
                status, ok = "PASS", True
            else:
                status, ok = "WARN", False  # usually = offline / firewall
        except Exception as exc:
            status, ok, got = "WARN", False, "exception: %s (offline?)" % exc
        checks.append(("PROXY       example.com via %s" % args.upstream, status, got))

        # 5. apex (optional)
        if args.include_apex:
            try:
                reply = query(args.host, args.port, args.zone, timeout=args.timeout)
                got = ", ".join(str(rr.rdata) for rr in reply.rr) or "<no answer>"
                ok = got == args.local_ip
            except Exception as exc:
                ok, got = False, "exception: %s" % exc
            checks.append(("apex        %s" % args.zone, "PASS" if ok else "FAIL", got))

        width = max(len(label) for label, _s, _d in checks)
        print("-" * 74)
        print(" SELF-TEST  (%s:%d, zone %s)" % (args.host, args.port, args.zone))
        print("-" * 74)
        for label, status, detail in checks:
            print(" [%s] %-*s %s" % (status, width, label, detail))
            if status == "FAIL":
                failures += 1
        stats = resolver.stats.snapshot()
        print("-" * 74)
        print(" counters: local=%d proxy=%d failed=%d" %
              (stats["local"], stats["proxy"], stats["failed"]))
        print(" RESULT  : %s" % ("ALL CRITICAL CHECKS PASSED" if failures == 0
                                 else "%d CHECK(S) FAILED" % failures))
        print("=" * 74)
    finally:
        stop_servers(servers)
    return 1 if failures else 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dns_simulator.py",
        description="Wildcard DNS server for *.local-saas.com that proxies "
                    "everything else to a public resolver.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="Interface/IP to bind.")
    parser.add_argument("--port", type=int, default=53,
                        help="UDP+TCP port to listen on (53 needs admin/root).")
    parser.add_argument("--zone", default="local-saas.com",
                        help="Sandbox zone answered locally (a leading '*.' is stripped).")
    parser.add_argument("--local-ip", default="127.0.0.1",
                        help="A record returned for every name inside the zone.")
    parser.add_argument("--include-apex", action="store_true",
                        help="Also resolve the bare apex '<zone>' (strict '*.' excludes it).")
    parser.add_argument("--upstream", default="8.8.8.8",
                        help="Public DNS server used to forward non-local queries.")
    parser.add_argument("--upstream-port", type=int, default=53,
                        help="Upstream DNS port.")
    parser.add_argument("--timeout", type=float, default=3.0,
                        help="Upstream query timeout in seconds.")
    parser.add_argument("--ttl", type=int, default=30,
                        help="TTL for local answers (keep low while developing).")
    parser.add_argument("--no-tcp", action="store_true",
                        help="Serve UDP only (skip TCP on the same port).")
    parser.add_argument("--self-test", action="store_true",
                        help="Start the server, run sanity checks, print results and exit.")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Verbosity of the decision log.")
    args = parser.parse_args(argv)

    zone = args.zone.strip().lower().rstrip(".")
    if zone.startswith("*."):
        zone = zone[2:]
    if not zone:
        parser.error("--zone must not be empty")
    args.zone = zone
    return args


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s.%(msecs)03d %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    # Third-party noise (dnslib protocol internals) stays quiet.
    logging.getLogger("dnslib").setLevel(logging.WARNING)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    configure_logging(args.log_level)

    if args.self_test:
        return run_self_test(args)

    resolver = MultiTenantResolver(args)
    servers = start_servers(resolver, args)
    print_banner(args)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        LOGGER.info("shutting down (Ctrl+C)")
    finally:
        stop_servers(servers)
        stats = resolver.stats.snapshot()
        print("-" * 74)
        print(" stats: local=%d proxy=%d failed=%d uptime=%ds"
              % (stats["local"], stats["proxy"], stats["failed"], stats["uptime"]))
        print(" stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
