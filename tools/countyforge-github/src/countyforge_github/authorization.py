"""Repository-permission authorization policy."""

from __future__ import annotations

from countyforge_github.contracts import ControlContracts, JsonObject

PERMISSIONS = frozenset({"admin", "maintain", "write", "triage", "read", "none"})
_LEGACY_PERMISSION = {"push": "write", "pull": "read"}


def normalized_permission(permission: JsonObject) -> str:
    """Prefer a recognized role name so maintain/triage are not flattened."""

    role = str(permission.get("role_name", "")).casefold()
    base = str(permission.get("permission", "none")).casefold()
    selected = role if role in PERMISSIONS else _LEGACY_PERMISSION.get(base, base)
    return selected if selected in PERMISSIONS else "none"


def authorize(
    *,
    actor_login: str,
    actor_id: int,
    actor_type: str,
    permission: JsonObject,
    team_slugs: list[str] | None = None,
    contracts: ControlContracts | None = None,
) -> JsonObject:
    """Return a complete sanitized authorization decision."""

    resolved = contracts or ControlContracts()
    policy = resolved.authorization_policy
    normalized = normalized_permission(permission)
    allowed_bots = {
        (str(item["login"]).casefold(), int(item["id"])) for item in policy["allowed_bots"]
    }
    allowed_teams = {str(item).casefold() for item in policy["allowed_teams"]}
    actor_key = (actor_login.casefold(), actor_id)
    teams = {team.casefold() for team in (team_slugs or [])}

    if actor_type == "Bot":
        allowed = actor_key in allowed_bots
        reason = "explicit_bot_allowed" if allowed else "bot_not_allowed"
    elif normalized in policy["allowed_permissions"]:
        allowed = True
        reason = "repository_permission_allowed"
    elif teams & allowed_teams:
        allowed = True
        reason = "explicit_team_allowed"
    else:
        allowed = False
        reason = "permission_denied"
    return {
        "actor": {"login": actor_login, "id": actor_id, "type": actor_type},
        "permission": normalized,
        "policy_version": int(policy["policy_version"]),
        "outcome": "allowed" if allowed else "denied",
        "reason_code": reason,
    }
