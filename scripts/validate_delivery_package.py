#!/usr/bin/env python3
"""Final truth gate for a video-to-sprite delivery package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from delivery_policy import (
    ONE_TO_ONE,
    SYNTHESIZED,
    authority_policy_errors,
    contract_policy_errors,
    delivery_mapping_errors,
    delivery_report_errors,
    mapping_manifest_errors,
    parent_frame_manifest_errors,
    visual_qa_report_errors,
)


def load_json(path: Path, label: str, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read {label}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label} must contain a JSON object")
        return {}
    return value


def accepted(report: dict[str, Any], label: str, errors: list[str]) -> None:
    if report.get("status") != "accepted":
        errors.append(f"{label} status is not accepted")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("authority_manifest", type=Path)
    parser.add_argument("contract", type=Path)
    parser.add_argument("mapping_manifest", type=Path)
    parser.add_argument("frame_validation_report", type=Path)
    parser.add_argument("temporal_validation_report", type=Path)
    parser.add_argument("delivery_report", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-correspondence-report", type=Path)
    parser.add_argument("--parent-frame-manifest", type=Path)
    parser.add_argument("--visual-qa-report", type=Path, required=True)
    args = parser.parse_args()

    errors: list[str] = []
    authority = load_json(args.authority_manifest, "authority manifest", errors)
    contract = load_json(args.contract, "frame contract", errors)
    mapping = load_json(args.mapping_manifest, "mapping manifest", errors)
    frame_report = load_json(
        args.frame_validation_report, "frame validation report", errors
    )
    temporal_report = load_json(
        args.temporal_validation_report, "temporal validation report", errors
    )
    delivery_report = load_json(args.delivery_report, "delivery report", errors)
    visual_qa_report = load_json(args.visual_qa_report, "visual QA report", errors)

    errors.extend(authority_policy_errors(authority))
    errors.extend(contract_policy_errors(contract))
    errors.extend(
        mapping_manifest_errors(
            mapping, expected_construction=authority.get("frameConstruction")
        )
    )
    errors.extend(delivery_report_errors(delivery_report, authority))
    errors.extend(delivery_mapping_errors(delivery_report, mapping))
    if authority.get("processingMode") == "gpt-image-alpha-repair":
        if not args.parent_frame_manifest:
            errors.append("alpha repair delivery requires --parent-frame-manifest")
        else:
            parent_manifest = load_json(
                args.parent_frame_manifest, "parent-frame manifest", errors
            )
            errors.extend(parent_frame_manifest_errors(parent_manifest, mapping))
    elif args.parent_frame_manifest:
        errors.append("parent-frame manifest is valid only for alpha repair delivery")
    errors.extend(visual_qa_report_errors(visual_qa_report))
    artifacts = visual_qa_report.get("artifacts", {})
    if isinstance(artifacts, dict):
        for name, value in artifacts.items():
            if not isinstance(value, str) or not value:
                continue
            path = Path(value)
            if not path.is_absolute():
                path = args.visual_qa_report.parent / path
            if not path.exists():
                errors.append(f"visual QA artifact does not exist: {name}")
    accepted(frame_report, "frame validation report", errors)
    accepted(temporal_report, "temporal validation report", errors)

    construction = authority.get("frameConstruction")
    correspondence_status = "not-provided"
    if args.source_correspondence_report:
        source_report = load_json(
            args.source_correspondence_report,
            "source correspondence report",
            errors,
        )
        correspondence_status = str(source_report.get("status", "missing-status"))
        if construction == ONE_TO_ONE:
            accepted(source_report, "source correspondence report", errors)
        elif construction == SYNTHESIZED and correspondence_status == "accepted":
            errors.append(
                "regenerative delivery must not use an accepted exact-source "
                "correspondence report"
            )
    elif construction == ONE_TO_ONE:
        errors.append("one-to-one delivery requires a source correspondence report")

    errors = list(dict.fromkeys(errors))
    report = {
        "status": "accepted" if not errors else "blocked",
        "frameConstruction": construction,
        "processingMode": authority.get("processingMode"),
        "backgroundRemovalTool": authority.get("backgroundRemovalTool"),
        "mappingRole": mapping.get("mappingRole"),
        "sourceCorrespondenceReportStatus": correspondence_status,
        "errors": errors,
        "inputs": {
            "authorityManifest": str(args.authority_manifest.resolve()),
            "contract": str(args.contract.resolve()),
            "mappingManifest": str(args.mapping_manifest.resolve()),
            "frameValidationReport": str(args.frame_validation_report.resolve()),
            "temporalValidationReport": str(args.temporal_validation_report.resolve()),
            "deliveryReport": str(args.delivery_report.resolve()),
            "sourceCorrespondenceReport": (
                str(args.source_correspondence_report.resolve())
                if args.source_correspondence_report
                else None
            ),
            "visualQaReport": str(args.visual_qa_report.resolve()),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "errors": len(errors)}, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
