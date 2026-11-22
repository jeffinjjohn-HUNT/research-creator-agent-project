"""URL validation and SSRF protection. Every outbound fetch (including each redirect hop) goes through here."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from packages.agent.schemas.models import Platform

ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURL(ValueError):
    pass


def _ip_is_blocked(ip: ipaddress._BaseAddress) -> bool:
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
            or ip.is_reserved or ip.is_unspecified)


def validate_url(url: str, *, resolve: bool = True) -> str:
    """Return the normalised URL or raise UnsafeURL. Blocks non-http(s), credentials, localhost/private IPs."""
    if not url or len(url) > 2048:
        raise UnsafeURL("empty or too long URL")
    p = urlparse(url.strip())
    if p.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURL(f"unsupported scheme {p.scheme!r}")
    if not p.hostname:
        raise UnsafeURL("missing host")
    if p.username or p.password:
        raise UnsafeURL("credentials in URL are not allowed")
    host = p.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise UnsafeURL("local hostnames are blocked")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _ip_is_blocked(literal):
            raise UnsafeURL("private/loopback IP blocked")
    elif resolve:
        try:
            infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
        except socket.gaierror as e:
            raise UnsafeURL(f"cannot resolve host: {e}") from e
        for info in infos:
            if _ip_is_blocked(ipaddress.ip_address(info[4][0])):
                raise UnsafeURL("host resolves to a private/loopback address")
    return p.geturl()


_PLATFORM_HOSTS = {
    Platform.instagram: ("instagram.com",),
    Platform.youtube: ("youtube.com", "youtu.be"),
    Platform.x: ("x.com", "twitter.com"),
    Platform.tiktok: ("tiktok.com",),
    Platform.linkedin: ("linkedin.com",),
    Platform.reddit: ("reddit.com", "redd.it"),
}


def detect_platform(url: str) -> Platform:
    host = (urlparse(url).hostname or "").lower()
    for platform, suffixes in _PLATFORM_HOSTS.items():
        if any(host == s or host.endswith("." + s) for s in suffixes):
            return platform
    return Platform.web
