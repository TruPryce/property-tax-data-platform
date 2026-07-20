"""Minimal GitHub REST port and a token-redacting standard-library adapter."""

from __future__ import annotations

import json
import re
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from countyforge_github.contracts import JsonObject
from countyforge_github.errors import ControlPlaneError

_ETAG_PATTERN = re.compile(r'(?:W/)?"[^\r\n"]+"')


def validate_etag(etag: object) -> str:
    """Validate one opaque HTTP entity tag without exposing transport secrets."""

    if not isinstance(etag, str) or len(etag) > 256 or _ETAG_PATTERN.fullmatch(etag) is None:
        raise ControlPlaneError("github_etag_malformed", "The canonical comment ETag is malformed.")
    return etag


class GitHubPort(Protocol):
    """Operations required by workflow orchestration and fake tests."""

    def repository_permission(self, repository: str, actor: str) -> JsonObject: ...

    def list_comments(self, repository: str, target_number: int) -> list[JsonObject]: ...

    def list_repository_comments(self, repository: str) -> list[JsonObject]: ...

    def get_comment(self, repository: str, comment_id: int) -> JsonObject: ...

    def update_comment_if_match(
        self, repository: str, comment_id: int, body: str, etag: str
    ) -> JsonObject: ...

    def pull_request(self, repository: str, number: int) -> JsonObject: ...

    def compare_commits(self, repository: str, base_sha: str, head_sha: str) -> JsonObject: ...

    def create_comment(self, repository: str, target_number: int, body: str) -> JsonObject: ...

    def update_comment(self, repository: str, comment_id: int, body: str) -> JsonObject: ...

    def workflow_run(self, repository: str, run_id: int) -> JsonObject: ...

    def cancel_workflow(self, repository: str, run_id: int) -> None: ...

    def dispatch_workflow(
        self, repository: str, workflow: str, ref: str, inputs: JsonObject
    ) -> None: ...

    def create_check(self, repository: str, payload: JsonObject) -> JsonObject: ...

    def update_check(self, repository: str, check_id: int, payload: JsonObject) -> JsonObject: ...


class GitHubRestClient:
    """Small API adapter; token values never enter exceptions or return values."""

    def __init__(
        self,
        token: str,
        *,
        api_url: str = "https://api.github.com",
        api_version: str = "2022-11-28",
    ) -> None:
        if not token:
            raise ControlPlaneError("github_token_missing", "GitHub API token is unavailable.")
        self._token = token
        self._api_url = api_url.rstrip("/")
        self._api_version = api_version

    def _request(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
        *,
        headers: dict[str, str] | None = None,
        conditional: bool = False,
    ) -> JsonObject | list[JsonObject] | None:
        value, _ = self._request_with_headers(
            method, path, payload, headers=headers, conditional=conditional
        )
        return value

    def _request_with_headers(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
        *,
        headers: dict[str, str] | None = None,
        conditional: bool = False,
    ) -> tuple[JsonObject | list[JsonObject] | None, dict[str, str]]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request_headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": self._api_version,
            "Content-Type": "application/json",
        }
        if headers:
            request_headers.update(headers)
        request = Request(
            f"{self._api_url}{path}",
            data=data,
            method=method,
            headers=request_headers,
        )
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed GitHub API root
                body = response.read()
                response_headers = {key.lower(): value for key, value in response.headers.items()}
        except HTTPError as error:
            if conditional and error.code == 412:
                raise ControlPlaneError(
                    "state_write_conflict",
                    "The canonical CountyForge comment changed concurrently.",
                ) from None
            raise ControlPlaneError(
                "github_api_error",
                "GitHub API request failed.",
                {"status": error.code},
                exit_code=5,
            ) from None
        except (URLError, TimeoutError):
            raise ControlPlaneError(
                "github_api_unavailable", "GitHub API is unavailable.", exit_code=5
            ) from None
        if not body:
            return None, response_headers
        try:
            value = json.loads(body)
        except json.JSONDecodeError:
            raise ControlPlaneError(
                "github_api_invalid_response", "GitHub API returned an invalid response."
            ) from None
        if isinstance(value, (dict, list)):
            return value, response_headers
        raise ControlPlaneError(
            "github_api_invalid_response", "GitHub API returned an invalid response."
        )

    def repository_permission(self, repository: str, actor: str) -> JsonObject:
        try:
            return cast(
                JsonObject,
                self._request("GET", f"/repos/{repository}/collaborators/{actor}/permission"),
            )
        except ControlPlaneError as error:
            if error.code == "github_api_error" and error.details.get("status") == 404:
                return {"permission": "none", "role_name": "none"}
            raise

    def _list_pages(self, path: str, *, max_pages: int = 10) -> list[JsonObject]:
        """Read a bounded GitHub collection or fail before losing canonical state."""

        items: list[JsonObject] = []
        separator = "&" if "?" in path else "?"
        for page in range(1, max_pages + 1):
            value = self._request("GET", f"{path}{separator}per_page=100&page={page}")
            if not isinstance(value, list):
                raise ControlPlaneError(
                    "github_api_invalid_response", "GitHub API returned an invalid response."
                )
            items.extend(value)
            if len(value) < 100:
                return items
        raise ControlPlaneError(
            "github_pagination_limit",
            "GitHub state lookup exceeded its bounded pagination limit.",
            exit_code=5,
        )

    def list_comments(self, repository: str, target_number: int) -> list[JsonObject]:
        return self._list_pages(f"/repos/{repository}/issues/{target_number}/comments")

    def list_repository_comments(self, repository: str) -> list[JsonObject]:
        return self._list_pages(f"/repos/{repository}/issues/comments?sort=updated&direction=desc")

    def get_comment(self, repository: str, comment_id: int) -> JsonObject:
        value, headers = self._request_with_headers(
            "GET", f"/repos/{repository}/issues/comments/{comment_id}"
        )
        etag = headers.get("etag")
        if etag is None:
            raise ControlPlaneError("github_etag_missing", "GitHub did not return a comment ETag.")
        validate_etag(etag)
        if not isinstance(value, dict):
            raise ControlPlaneError(
                "github_api_invalid_response", "GitHub returned an invalid comment response."
            )
        result = value
        result["etag"] = etag
        return result

    def pull_request(self, repository: str, number: int) -> JsonObject:
        return cast(JsonObject, self._request("GET", f"/repos/{repository}/pulls/{number}"))

    def compare_commits(self, repository: str, base_sha: str, head_sha: str) -> JsonObject:
        return cast(
            JsonObject,
            self._request("GET", f"/repos/{repository}/compare/{base_sha}...{head_sha}"),
        )

    def create_comment(self, repository: str, target_number: int, body: str) -> JsonObject:
        return cast(
            JsonObject,
            self._request(
                "POST", f"/repos/{repository}/issues/{target_number}/comments", {"body": body}
            ),
        )

    def update_comment(self, repository: str, comment_id: int, body: str) -> JsonObject:
        return cast(
            JsonObject,
            self._request(
                "PATCH", f"/repos/{repository}/issues/comments/{comment_id}", {"body": body}
            ),
        )

    def update_comment_if_match(
        self, repository: str, comment_id: int, body: str, etag: str
    ) -> JsonObject:
        validate_etag(etag)
        value, headers = self._request_with_headers(
            "PATCH",
            f"/repos/{repository}/issues/comments/{comment_id}",
            {"body": body},
            headers={"If-Match": etag},
            conditional=True,
        )
        response_etag = headers.get("etag")
        if response_etag is None:
            raise ControlPlaneError(
                "github_etag_missing", "GitHub did not return the updated comment ETag."
            )
        validate_etag(response_etag)
        if not isinstance(value, dict):
            raise ControlPlaneError(
                "github_api_invalid_response", "GitHub returned an invalid comment response."
            )
        result = value
        result["etag"] = response_etag
        return result

    def workflow_run(self, repository: str, run_id: int) -> JsonObject:
        return cast(JsonObject, self._request("GET", f"/repos/{repository}/actions/runs/{run_id}"))

    def cancel_workflow(self, repository: str, run_id: int) -> None:
        self._request("POST", f"/repos/{repository}/actions/runs/{run_id}/cancel")

    def dispatch_workflow(
        self, repository: str, workflow: str, ref: str, inputs: JsonObject
    ) -> None:
        self._request(
            "POST",
            f"/repos/{repository}/actions/workflows/{workflow}/dispatches",
            {"ref": ref, "inputs": inputs},
        )

    def create_check(self, repository: str, payload: JsonObject) -> JsonObject:
        return cast(JsonObject, self._request("POST", f"/repos/{repository}/check-runs", payload))

    def update_check(self, repository: str, check_id: int, payload: JsonObject) -> JsonObject:
        return cast(
            JsonObject,
            self._request("PATCH", f"/repos/{repository}/check-runs/{check_id}", payload),
        )
