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
    def __init__(self, body: bytes, headers: dict[str, str]) -> None:
        self._body = body
        self.headers = headers

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_comment_get_captures_etag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        github_api,
        "urlopen",
        lambda *_args, **_kwargs: _Response(
            b'{"id": 7, "body": "status"}', {"ETag": '"comment-7-4"'}
        ),
    )
    result = GitHubRestClient("synthetic-token").get_comment("owner/repo", 7)
    assert result["etag"] == '"comment-7-4"'


def test_conditional_patch_sends_exact_if_match(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str | None] = {}

    def fake_urlopen(request: object, **_kwargs: object) -> _Response:
        assert hasattr(request, "get_header")
        captured["etag"] = request.get_header("If-match")  # type: ignore[attr-defined]
        return _Response(b'{"id": 7, "body": "updated"}', {"ETag": '"comment-7-5"'})

    monkeypatch.setattr(github_api, "urlopen", fake_urlopen)
    result = GitHubRestClient("synthetic-token").update_comment_if_match(
        "owner/repo", 7, "updated", 'W/"comment-7-4"'
    )
    assert captured["etag"] == 'W/"comment-7-4"'
    assert result["body"] == "updated"


def test_conditional_patch_412_is_state_conflict_without_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(*_args: object, **_kwargs: object) -> None:
        from urllib.error import HTTPError

        raise HTTPError("https://api.github.com", 412, "precondition", {}, io.BytesIO())

    monkeypatch.setattr(github_api, "urlopen", fake_urlopen)
    with pytest.raises(ControlPlaneError) as raised:
        GitHubRestClient("secret-token").update_comment_if_match(
            "owner/repo", 7, "updated", '"comment-7-4"'
        )
    assert raised.value.code == "state_write_conflict"
    assert "secret-token" not in str(raised.value)


@pytest.mark.parametrize("etag", [None, "comment-7-4", '"bad\nvalue"'])
def test_comment_get_missing_or_malformed_etag_fails_closed(
    monkeypatch: pytest.MonkeyPatch, etag: str | None
) -> None:
    headers = {} if etag is None else {"ETag": etag}
    monkeypatch.setattr(
        github_api,
        "urlopen",
        lambda *_args, **_kwargs: _Response(b'{"id": 7, "body": "status"}', headers),
    )
    with pytest.raises(ControlPlaneError) as raised:
        GitHubRestClient("synthetic-token").get_comment("owner/repo", 7)
    assert raised.value.code in {"github_etag_missing", "github_etag_malformed"}
