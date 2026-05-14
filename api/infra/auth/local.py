"""Local auth provider. Single-user, no verification."""

from fastapi import Request


class LocalAuthProvider:
    def __init__(self, user_id: str):
        self._user_id = user_id

    async def get_current_user(self, request: Request) -> str:
        return self._user_id
