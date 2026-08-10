"""Shared test support for the CountyForge GitHub control-plane suites.

Deliberately not `conftest.py`: two test packages each have one, so importing a
helper by that name resolves to whichever package pytest collected first. This
module's name is unique across the repository.
"""

from __future__ import annotations

import tempfile
from pathlib import Path


def controlled_contract_root() -> Path:
    """A contract root whose capability inventory the tests control.

    `Path.cwd()` reads the working tree, so promoting a spec -- the ordinary
    OpenSpec archival step -- silently turned "no capability is declared" into
    `affected_capability_already_exists` across unrelated tests, locally only,
    while CI stayed green. Now that `collin-cad-source-contract` is archived
    into `openspec/specs/`, that is the difference between passing and failing
    rather than a hypothesis.

    `.ai` is linked to the real tree so schemas and policy stay authoritative;
    only `openspec/specs` is controlled, and it starts empty.
    """

    root = Path(tempfile.mkdtemp(prefix="countyforge-contract-root-"))
    (root / ".ai").symlink_to((Path.cwd() / ".ai").resolve(), target_is_directory=True)
    (root / "openspec" / "specs").mkdir(parents=True)
    return root
