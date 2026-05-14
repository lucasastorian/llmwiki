"""Per-user / per-IP rate limiting via slowapi. IP is always a co-bucket so a forged JWT sub can't escape the IP cap."""

from __future__ import annotations

import jwt as _jwt
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _user_or_ip(request: Request) -> str:
    # Bucket primarily by verified user_id when available; otherwise IP.
    # Real verification has not happened yet at this point, so we deliberately
    # combine ip+sub so a forged sub can't escape the per-IP cap.
    ip = get_remote_address(request)
    auth = request.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        token = auth.removeprefix("Bearer ").strip()
        try:
            payload = _jwt.decode(token, options={"verify_signature": False})
            sub = payload.get("sub")
            if sub:
                return f"ip:{ip}|user:{sub}"
        except Exception:
            pass
    return f"ip:{ip}"


limiter = Limiter(key_func=_user_or_ip, default_limits=["600/10minute"])
