"""Auth provider protocol definition."""

from typing import Protocol, runtime_checkable

from fastapi import Request


@runtime_checkable
class AuthProvider(Protocol):

    async def get_current_user(self, request: Request) -> str:
        """Authenticate the request and return the user_id."""
        ...
