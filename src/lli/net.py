"""
Networking helpers for LLM Interceptor.

This module is intentionally dependency-free (stdlib only) and focuses on
deriving a useful "advertise address" when binding to wildcard interfaces
like 0.0.0.0 / :: (similar to how FastAPI prints a reachable LAN URL).
"""

from __future__ import annotations

import ipaddress
import socket


def _is_publicly_unhelpful(ip: str) -> bool:
    """Return True if the ip is loopback/unspecified/link-local."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True

    return bool(
        addr.is_loopback
        or addr.is_unspecified
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
    )


def detect_primary_ipv4() -> str | None:
    """
    Best-effort detection of the primary LAN IPv4 address.

    Uses a UDP "connect" trick which does not require external connectivity and
    does not send packets, but selects the outbound interface/address.
    """
    # 1) UDP connect trick (most reliable for "default route")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Any routable IP/port works; no packets are sent for UDP connect.
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not _is_publicly_unhelpful(ip):
                return ip
    except OSError:
        pass

    # 2) Hostname resolution fallback
    try:
        hostname = socket.gethostname()
        infos = socket.getaddrinfo(hostname, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
        for info in infos:
            ip = info[4][0]
            if ip and not _is_publicly_unhelpful(ip):
                return ip
    except OSError:
        pass

    return None


def reachable_host_for_listen_host(listen_host: str) -> str:
    """
    Return a "reachable" host string to show users.

    - When listening on 0.0.0.0 (all interfaces), return the detected LAN IPv4.
    - Otherwise return listen_host as-is.
    """
    if listen_host == "0.0.0.0":
        return detect_primary_ipv4() or "127.0.0.1"
    return listen_host
