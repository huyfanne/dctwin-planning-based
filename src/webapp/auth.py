from __future__ import annotations

import os
from typing import Optional

from fastapi import Header, HTTPException

ROLE_LEVELS = {"operator": 1, "expert": 2}


class TokenAuth:
    """Bearer-token auth with two roles (operator < expert)."""

    def __init__(self, tokens: dict[str, str]):
        self.tokens = tokens  # token -> role

    @classmethod
    def from_env(cls) -> "TokenAuth":
        tokens = {}
        if os.environ.get("OPERATOR_TOKEN"):
            tokens[os.environ["OPERATOR_TOKEN"]] = "operator"
        if os.environ.get("EXPERT_TOKEN"):
            tokens[os.environ["EXPERT_TOKEN"]] = "expert"
        return cls(tokens)

    def role_for(self, token: str) -> Optional[str]:
        return self.tokens.get(token)

    def check(self, authorization: Optional[str], min_role: str) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization.split(" ", 1)[1]
        role = self.role_for(token)
        if role is None:
            raise HTTPException(status_code=401, detail="invalid token")
        if ROLE_LEVELS[role] < ROLE_LEVELS[min_role]:
            raise HTTPException(status_code=403, detail=f"requires {min_role} role")
        return role

    def require(self, min_role: str):
        """Return a FastAPI dependency enforcing `min_role`."""
        def dep(authorization: Optional[str] = Header(default=None)) -> str:
            return self.check(authorization, min_role)
        return dep
