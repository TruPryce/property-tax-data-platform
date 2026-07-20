"""Bounded, no-network GitHub REST pagination tests."""

from __future__ import annotations

import io

import pytest
from countyforge_github import github_api
from countyforge_github.contracts import JsonObject
from countyforge_github.errors import ControlPlaneError
from countyforge_github.github_api import GitHubRestClient


class FakePagedClient(GitHubRestClient):
    def __init__(self, pages: list[list[JsonObject]]) -> None:
        super().__init__("synthetic-token")
        self.pages = pages
        self.paths: list[str] = []

    def _request(
        self, method: str, path: str, payload: JsonObject | None = None
    ) -> JsonObject | list[JsonObject] | None:
        self.paths.append(path)
        return self.pages[len(self.paths) - 1]


def test_comment_lookup_paginates_until_short_page() -> None:
    first = [{"id": index} for index in range(100)]
    second = [{"id": 100}]
    client = FakePagedClient([first, second])
    result = client.list_comments("owner/repo", 5)
    assert len(result) == 101
    assert client.paths == [
        "/repos/owner/repo/issues/5/comments?per_page=100&page=1",
        "/repos/owner/repo/issues/5/comments?per_page=100&page=2",
    ]


def test_comment_lookup_fails_closed_at_bounded_limit() -> None:
    full_page: list[JsonObject] = [{"id": index} for index in range(100)]
    client = FakePagedClient([full_page] * 10)
    with pytest.raises(ControlPlaneError) as raised:
        client.list_repository_comments("owner/repo")
    assert raised.value.code == "github_pagination_limit"
    assert len(client.paths) == 10


class _Response:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.headers = headers or {}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_comment_update_sends_plain_patch_without_if_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # GitHub does not honor If-Match/412 on the issue-comment update endpoint, so the
    # adapter must never send a conditional header. Serialization is provided by the
    # shared countyforge-state-* workflow lane instead.
    captured: dict[str, object] = {}

    def fake_urlopen(request: object, **_kwargs: object) -> _Response:
        assert hasattr(request, "get_header")
        captured["if_match"] = request.get_header("If-match")  # type: ignore[attr-defined]
        captured["method"] = request.get_method()  # type: ignore[attr-defined]
        return _Response(b'{"id": 7, "body": "updated"}')

    monkeypatch.setattr(github_api, "urlopen", fake_urlopen)
    result = GitHubRestClient("synthetic-token").update_comment("owner/repo", 7, "updated")
    assert captured["if_match"] is None
    assert captured["method"] == "PATCH"
    assert result["body"] == "updated"


def test_comment_get_returns_body_without_requiring_an_etag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        github_api,
        "urlopen",
        lambda *_args, **_kwargs: _Response(b'{"id": 7, "body": "status"}'),
    )
    result = GitHubRestClient("synthetic-token").get_comment("owner/repo", 7)
    assert result == {"id": 7, "body": "status"}
    assert "etag" not in result


def test_comment_update_error_never_leaks_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(*_args: object, **_kwargs: object) -> None:
        from urllib.error import HTTPError

        raise HTTPError("https://api.github.com", 422, "unprocessable", {}, io.BytesIO())

    monkeypatch.setattr(github_api, "urlopen", fake_urlopen)
    with pytest.raises(ControlPlaneError) as raised:
        GitHubRestClient("secret-token").update_comment("owner/repo", 7, "updated")
    assert raised.value.code == "github_api_error"
    assert "secret-token" not in str(raised.value)
    assert "secret-token" not in repr(raised.value.details)
