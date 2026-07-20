"""Bounded, no-network GitHub REST pagination tests."""

from __future__ import annotations

import pytest
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
