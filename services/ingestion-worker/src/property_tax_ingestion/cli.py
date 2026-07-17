"""Developer-facing ingestion worker commands."""

import argparse
import json
from collections.abc import Sequence

from property_tax_adapters.sources.texas import all_sources


def _county_payload() -> list[dict[str, object]]:
    return [
        {
            "slug": source.county.slug,
            "name": source.county.name,
            "state": source.county.state_code,
            "fips": source.county.fips,
            "official_url": source.official_url,
            "acquisition_method": source.acquisition_method,
            "parser_id": source.parser_id,
            "production_ready": source.production_ready,
        }
        for source in all_sources()
    ]


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser without performing runtime work."""

    parser = argparse.ArgumentParser(prog="property-tax-ingestion")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("counties", help="print registered county sources as JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one ingestion worker command."""

    args = build_parser().parse_args(argv)
    if args.command == "counties":
        print(json.dumps(_county_payload(), indent=2))
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")
