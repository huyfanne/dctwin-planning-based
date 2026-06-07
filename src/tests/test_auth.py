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


def test_empty_tokens_with_insecure_disables_auth():
    # No tokens configured + explicit insecure opt-in -> auth is disabled:
    # any request passes as "expert", even with no Authorization header.
    auth = TokenAuth({}, insecure=True)
    assert auth.check(None, "operator") == "expert"
    assert auth.check(None, "expert") == "expert"
    assert auth.check("Bearer anything", "expert") == "expert"


def test_no_tokens_fail_closed(monkeypatch):
    monkeypatch.delenv("OPERATOR_TOKEN", raising=False)
    monkeypatch.delenv("EXPERT_TOKEN", raising=False)
    monkeypatch.delenv("DTWIN_INSECURE", raising=False)
    auth = TokenAuth.from_env()
    with pytest.raises(HTTPException) as e:
        auth.check(authorization=None, min_role="operator")
    assert e.value.status_code == 401


def test_insecure_opt_in_allows_all(monkeypatch):
    monkeypatch.delenv("OPERATOR_TOKEN", raising=False)
    monkeypatch.delenv("EXPERT_TOKEN", raising=False)
    monkeypatch.setenv("DTWIN_INSECURE", "1")
    auth = TokenAuth.from_env()
    assert auth.check(authorization=None, min_role="expert") == "expert"
