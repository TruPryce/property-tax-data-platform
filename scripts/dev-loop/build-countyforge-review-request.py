"""Build one strict local review request from immutable Git facts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--packet-provenance", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--provider", choices=("openai", "sakana"), required=True)
    parser.add_argument("--model-ref")
    parser.add_argument("--reasoning-effort", choices=("high", "xhigh"), default="xhigh")
    parser.add_argument("--openspec-change")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile = json.loads(
        (args.repo_root / ".ai/profiles/review.packet-only.v1.json").read_text(encoding="utf-8")
    )
    catalog = json.loads(
        (args.repo_root / ".ai/providers/catalog.v1.json").read_text(encoding="utf-8")
    )
    defaults = {"openai": "openai.gpt-5.6", "sakana": "sakana.fugu-ultra"}
    model_ref = args.model_ref or defaults[args.provider]
    model = next(
        (
            entry
            for entry in catalog["models"]
            if entry["logical_ref"] == model_ref and entry["provider"] == args.provider
        ),
        None,
    )
    if model is None:
        raise SystemExit("selected provider/model reference is not in the CountyForge catalog")
    packet = args.packet.resolve(strict=True)
    packet_provenance = args.packet_provenance.resolve(strict=True)

    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    request = {
        "contract_version": 1,
        "run_id": args.run_id,
        "trigger": {"type": "manual", "actor": {"id": args.actor}},
        "repository": {
            "full_name": "TruPryce/property-tax-data-platform",
            "base_sha": args.base_sha,
            "head_sha": args.head_sha,
        },
        "display_metadata": {"branch": args.branch},
        "openspec_change": args.openspec_change,
        "mode": "review",
        "profile": {"id": profile["profile_id"], "version": profile["profile_version"]},
        "prompt": {"id": profile["prompt"]["id"], "version": profile["prompt"]["version"]},
        "provider": {
            "id": args.provider,
            "model_ref": model_ref,
            "codex_cli_version": profile["container"]["codex_cli_version"],
        },
        "reasoning_effort": args.reasoning_effort,
        "budget_overrides": {},
        "input": {
            "packet_path": str(packet),
            "packet_sha256": sha256(packet),
            "packet_provenance_path": str(packet_provenance),
            "packet_provenance_sha256": sha256(packet_provenance),
        },
        "expected_output_schema": profile["output_schema"],
        "requested_artifacts": [
            "codex-prepr-review.md",
            "countyforge-request.provenance.json",
            "countyforge-profile.snapshot.json",
            "countyforge-run-event.ndjson",
            "countyforge-run-summary.json",
            "countyforge-run-metrics.prom",
        ],
    }
    print(json.dumps(request, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
