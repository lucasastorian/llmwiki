"""Pre-authentication IP rate limiting via slowapi."""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _user_or_ip(request: Request) -> str:
    # Middleware runs before JWT verification. Never key a security limit from
    # unverified JWT claims: an attacker can mint arbitrary `sub` values and
    # create an unlimited number of buckets from one address.
    ip = get_remote_address(request)
    return f"ip:{ip}"


limiter = Limiter(key_func=_user_or_ip, default_limits=["600/10minute"])
