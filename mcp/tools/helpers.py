import os
import logging
from fnmatch import fnmatch

import aioboto3
from mcp.server.fastmcp import Context
from mcp.server.auth.middleware.auth_context import get_access_token

from config import settings
from db import scoped_queryrow

logger = logging.getLogger(__name__)

MAX_LIST = 50
MAX_SEARCH = 20

def get_user_id(ctx: Context) -> str:
    local_id = os.environ.get("SUPAVAULT_USER_ID")
    if local_id:
        import sys
        if "local_server" not in sys.modules:
            raise RuntimeError("SUPAVAULT_USER_ID is set but local_server is not loaded — refusing to bypass auth")
        return local_id

    access_token = get_access_token()
    if not access_token:
        raise RuntimeError("Not authenticated")

    if access_token.client_id:
        return access_token.client_id

    raise RuntimeError("No user identifier in token")


def deep_link(kb_slug: str, path: str, filename: str) -> str:
    full = (path.rstrip("/") + "/" + filename).lstrip("/")
    return f"{settings.APP_URL}/wikis/{kb_slug}/{full}"


def glob_match(filepath: str, pattern: str) -> bool:
    return fnmatch(filepath, pattern)


def resolve_path(path: str) -> tuple[str, str]:
    path_clean = path.lstrip("/")
    if "/" in path_clean:
        dir_path = "/" + path_clean.rsplit("/", 1)[0] + "/"
        filename = path_clean.rsplit("/", 1)[1]
    else:
        dir_path = "/"
        filename = path_clean
    return dir_path, filename


async def resolve_kb(user_id: str, slug: str) -> dict | None:
    return await scoped_queryrow(
        user_id,
        "SELECT id, name, slug FROM knowledge_bases WHERE slug = $1",
        slug,
    )


_s3_session = None


def _get_s3_session():
    global _s3_session
    if _s3_session is None and settings.AWS_ACCESS_KEY_ID:
        _s3_session = aioboto3.Session(
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
    return _s3_session


async def load_s3_bytes(key: str) -> bytes | None:
    session = _get_s3_session()
    if not session:
        return None
    try:
        async with session.client("s3") as s3:
            resp = await s3.get_object(Bucket=settings.S3_BUCKET, Key=key)
            return await resp["Body"].read()
    except Exception as e:
        logger.warning("Failed to load S3 key %s: %s", key, e)
        return None


def parse_page_range(pages_str: str, max_page: int) -> list[int]:
    result = set()
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            s, e = int(start.strip()), int(end.strip())
            for p in range(max(1, s), min(max_page, e) + 1):
                result.add(p)
        elif part.isdigit():
            p = int(part)
            if 1 <= p <= max_page:
                result.add(p)
    return sorted(result)
