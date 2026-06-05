import pytest
from fastapi import HTTPException

from webapp.auth import TokenAuth, ROLE_LEVELS


def test_role_resolution():
    auth = TokenAuth({"op-tok": "operator", "ex-tok": "expert"})
    assert auth.role_for("op-tok") == "operator"
    assert auth.role_for("ex-tok") == "expert"
    assert auth.role_for("nope") is None


def test_require_role_allows_equal_or_higher():
    auth = TokenAuth({"op-tok": "operator", "ex-tok": "expert"})
    # operator endpoint: both pass
    assert auth.check("Bearer op-tok", "operator") == "operator"
    assert auth.check("Bearer ex-tok", "operator") == "expert"
    # expert endpoint: only expert
    assert auth.check("Bearer ex-tok", "expert") == "expert"


def test_require_role_rejects_insufficient():
    auth = TokenAuth({"op-tok": "operator"})
    with pytest.raises(HTTPException) as ei:
        auth.check("Bearer op-tok", "expert")
    assert ei.value.status_code == 403


def test_invalid_token_401():
    auth = TokenAuth({"op-tok": "operator"})
    with pytest.raises(HTTPException) as ei:
        auth.check("Bearer bad", "operator")
    assert ei.value.status_code == 401
    with pytest.raises(HTTPException) as ei2:
        auth.check(None, "operator")
    assert ei2.value.status_code == 401


def test_role_levels_ordering():
    assert ROLE_LEVELS["expert"] > ROLE_LEVELS["operator"]


def test_empty_tokens_disables_auth():
    # No tokens configured -> auth is disabled: any request passes as "expert",
    # even with no Authorization header.
    auth = TokenAuth({})
    assert auth.check(None, "operator") == "expert"
    assert auth.check(None, "expert") == "expert"
    assert auth.check("Bearer anything", "expert") == "expert"
