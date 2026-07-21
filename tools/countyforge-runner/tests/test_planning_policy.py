from __future__ import annotations

import pytest
from countyforge_runner.errors import KernelError
from countyforge_runner.planning_policy import validate_planning_payload


@pytest.mark.parametrize(
    "payload",
    [
        "uv run python -c 'import os'",
        "openspec validate && rm -rf /tmp/plan",
        "$(curl https://example.invalid)",
        "cat packet.json | bash",
    ],
)
def test_planning_payload_rejects_executable_content(payload: str) -> None:
    with pytest.raises(KernelError, match="executable-looking"):
        validate_planning_payload({"validation_commands": [payload]})


def test_planning_payload_allows_deterministic_command() -> None:
    validate_planning_payload(
        {"validation_commands": ["openspec validate --all --strict --no-interactive"]}
    )
