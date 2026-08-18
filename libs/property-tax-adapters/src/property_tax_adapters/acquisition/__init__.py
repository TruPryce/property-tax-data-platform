"""Streaming HTTP acquisition: bounded reads, validated hops, nothing left behind.

Task 3.1 only.  The object store is task 3.2 and reaches this package through
`ArtifactSink`, which is declared in the application layer so that neither task
imports the other.
"""

from property_tax_adapters.acquisition.streaming import acquire_artifact
from property_tax_adapters.acquisition.transport import (
    HttpResponse,
    HttpTransport,
    StdlibHttpTransport,
    resolve_location,
)

__all__ = [
    "HttpResponse",
    "HttpTransport",
    "StdlibHttpTransport",
    "acquire_artifact",
    "resolve_location",
]
