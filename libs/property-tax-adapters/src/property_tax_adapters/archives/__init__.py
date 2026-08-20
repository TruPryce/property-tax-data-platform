"""Archive inspection and bounded extraction."""

from property_tax_adapters.archives.zip_inspection import (
    VerifiedArchive,
    inspect_zip,
    open_archive,
)

__all__ = ["VerifiedArchive", "inspect_zip", "open_archive"]
