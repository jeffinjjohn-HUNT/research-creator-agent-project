import socket

import pytest


@pytest.fixture(autouse=True)
def fake_public_dns(monkeypatch):
    """Tests must not depend on real DNS. Hostnames resolve to a public documentation-range IP
    (192.0.2.0/24 is 'reserved' for docs, so use a routable public address instead)."""
    real = socket.getaddrinfo

    def fake(host, port, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 80))]

    monkeypatch.setattr(socket, "getaddrinfo", fake)
