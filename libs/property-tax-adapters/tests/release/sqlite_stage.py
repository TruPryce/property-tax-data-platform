"""A file-backed stage proving the conformance suite has a passing implementation.

This is a **test fixture**, not a production stage. The suite is the contract;
durable persistence and the production unique index are owned by bootstrap tasks
3.4 and 3.5.

It uses the standard-library `sqlite3` only, so it adds no dependency, and it
takes a caller-supplied directory with an explicit page ceiling, cleaning up on
success, on failure, and on retry.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType

from property_tax_adapters.release import DuplicateRecordKey
from property_tax_adapters.sources.contracts import AppraisalSourceRecord

#: An explicit ceiling, so a runaway release cannot fill the caller's disk.
DEFAULT_MAX_PAGES = 4_096


class SqliteReleaseStage:
    """Writes into an uncommitted transaction; commit is what makes it visible."""

    def __init__(self, directory: Path, *, max_pages: int = DEFAULT_MAX_PAGES) -> None:
        self._path = Path(directory) / "release-stage.sqlite3"
        self._max_pages = max_pages
        self._connection: sqlite3.Connection | None = None
        self._committed = False

    def __enter__(self) -> SqliteReleaseStage:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.unlink(missing_ok=True)
        connection = sqlite3.connect(self._path, isolation_level=None)
        connection.execute(f"PRAGMA max_page_count = {self._max_pages}")
        connection.execute(
            "CREATE TABLE staged ("
            "  account_id TEXT NOT NULL,"
            "  appraisal_year INTEGER NOT NULL,"
            "  source_row_number INTEGER NOT NULL,"
            "  UNIQUE (account_id, appraisal_year)"
            ")"
        )
        # Explicit transaction control: Python implicitly commits before a
        # SAVEPOINT under the legacy isolation modes, which would make staged
        # rows visible before the commit that is supposed to reveal them.
        connection.execute("BEGIN")
        self._connection = connection
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # May not fail after either a commit or an abort, which is what makes it
        # safe to run after the only step that changes visibility.
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if not self._committed:
            self._path.unlink(missing_ok=True)

    def write(self, records: Sequence[AppraisalSourceRecord]) -> None:
        """All or nothing: a savepoint per call, rolled back if any row fails.

        Without it a failure partway through a multi-record row would leave the
        prefix staged while the processor counted none of it.
        """

        connection = self._require_connection()
        connection.execute("SAVEPOINT row")
        try:
            for record in records:
                connection.execute(
                    "INSERT INTO staged VALUES (?, ?, ?)",
                    (
                        record.source_account_id,
                        record.appraisal_year,
                        record.provenance.source_row_number,
                    ),
                )
        except sqlite3.IntegrityError as error:
            connection.execute("ROLLBACK TO row")
            connection.execute("RELEASE row")
            raise DuplicateRecordKey from error
        except Exception:
            connection.execute("ROLLBACK TO row")
            connection.execute("RELEASE row")
            raise
        connection.execute("RELEASE row")

    def finalize(self) -> None:
        """This index is eager, so duplicates surfaced at write."""

        self._require_connection()

    def abort(self) -> None:
        connection = self._require_connection()
        connection.execute("ROLLBACK")

    def commit(self) -> None:
        connection = self._require_connection()
        connection.execute("COMMIT")
        self._committed = True

    def visible_records(self) -> list[tuple[str, int, int]]:
        """What a separate connection can see — the definition of visible."""

        if not self._path.exists():
            return []
        with sqlite3.connect(self._path) as reader:
            try:
                return list(reader.execute("SELECT * FROM staged"))
            except sqlite3.OperationalError:
                return []

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("stage used outside its context manager")
        return self._connection
