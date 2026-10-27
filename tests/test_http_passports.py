"""Per-actor HTTP passports in mcp_http (additive; grok default unchanged)."""

import secrets

import pytest

import mcp_http


@pytest.fixture
def rdir(tmp_path, monkeypatch):
    tok = tmp_path / "mcp-http.token"
    tok.write_text("G" * 43 + "\n")
    monkeypatch.setattr(mcp_http, "TOKEN_PATH", tok)
    (tmp_path / "stdio-actors").write_text("nicodemus\nsentinel_demi\n")
    return tmp_path


def _named(d, actor, body=None):
    body = body or secrets.token_urlsafe(32)
    (d / f"mcp-http.{actor}.token").write_text(body + "\n")
    return body


def test_default_token_resolves_to_default_host(rdir):
    assert mcp_http._resolve_bearer("G" * 43) is None


def test_named_token_maps_to_actor(rdir):
    t = _named(rdir, "nicodemus")
    assert mcp_http._resolve_bearer(t) == "nicodemus"


def test_off_roster_named_token_rejected(rdir):
    t = _named(rdir, "mallory")
    with pytest.raises(LookupError):
        mcp_http._resolve_bearer(t)


def test_named_grok_file_cannot_shadow_default(rdir):
    t = _named(rdir, "grok")
    with pytest.raises(LookupError):
        mcp_http._resolve_bearer(t)


def test_short_or_empty_or_bogus_rejected(rdir):
    _named(rdir, "sentinel_demi", "short")
    for bad in ("", "short", "bogus" * 10, "G" * 42):
        with pytest.raises(LookupError):
            mcp_http._resolve_bearer(bad)


def test_host_binds_actor_per_request(rdir, monkeypatch):
    made = []

    class FakeHost:
        def __init__(self, actor=None, **kw):
            self.actor = actor or "grok"
            made.append(self.actor)

    monkeypatch.setattr(mcp_http, "AssuredPlaneHost", FakeHost)
    monkeypatch.setattr(mcp_http, "_host", None)
    monkeypatch.setattr(mcp_http, "_actor_hosts", {})
    mcp_http._req.actor = None
    assert mcp_http.host().actor == "grok"
    mcp_http._req.actor = "nicodemus"
    assert mcp_http.host().actor == "nicodemus"
    assert mcp_http.host() is mcp_http.host()
    mcp_http._req.actor = None
    assert mcp_http.host().actor == "grok"
    assert made == ["grok", "nicodemus"]
