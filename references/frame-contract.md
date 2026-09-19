# Frame contract

The frame contract makes source-frame lineage, processing limits, and placement measurable.

## Required lineage fields

- `frameConstruction`: normally `one-to-one-source`; `synthesized` only with explicit approval
- `backgroundRemovalTool`: independently selected as `rembg` or `GPT Image`
- `processingMode`: `rembg-extraction`, `gpt-image-per-frame-edit`, or approved `gpt-image-regeneration`
- `pixelAuthority` and `poseAuthority`
- `mappingRole`: `selected-source-frame-authority` for one-to-one processing
- `sourceFrameManifest`: mandatory for one-to-one processing with either tool
- `sourceCorrespondenceRequired`: true for one-to-one processing
- `perFrameAuthorityDirectory`: decoded selected native frames

The source manifest records output/native-frame order, timestamp, source filename, source SHA-256, classification, and whether RGB or geometry may change. One-to-one records require `sourceFrameRequired: true`, `geometryChanged: false`, and no holds or interpolation.

Use `motionReferenceManifest` only for explicitly approved synthesized motion. It cannot satisfy source correspondence.

## Placement and visual fields

Record canvas, pivot, ground line, two-foot regions when relevant, visible bounds, locked and moving regions, required semantic regions, negative spaces, state templates, temporal limits, and numerical tolerances.

Build the contract from the approved proof and source manifest. Run `validate_and_diagnose.py` for every frame, preserve failed frames and diagnostics, and use targeted repairs. Global metrics cannot authorize a pose that differs from its mapped source frame.
