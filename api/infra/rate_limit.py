"""Pre-authentication IP rate limiting via slowapi."""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _client_ip(request: Request) -> str:
    # Runs before JWT verification: keying on an unverified `sub` would let one address mint unlimited buckets.
    ip = get_remote_address(request)
    return f"ip:{ip}"


limiter = Limiter(key_func=_client_ip, default_limits=["600/10minute"])
