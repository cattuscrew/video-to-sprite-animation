# Frame contract

The frame contract makes source-frame lineage, processing limits, and placement measurable.

## Required lineage fields

- `frameConstruction`: normally `one-to-one-source`; `synthesized` only with explicit approval
- `backgroundRemovalTool`: fixed to `GPT Image`
- `processingMode`: `gpt-image-per-frame-edit`, or approved `gpt-image-regeneration`
- `imageExecutionInterface`: fixed to `built-in-image-tool`; external APIs are forbidden
- `credentialMode`: fixed to `none`; never request, discover, or configure an API key
- `pixelAuthority` and `poseAuthority`
- `mappingRole`: `selected-source-frame-authority` for one-to-one processing
- `sourceFrameManifest`: mandatory for one-to-one processing with either tool
- `sourceCorrespondenceRequired`: true for one-to-one processing
- `perFrameAuthorityDirectory`: decoded selected native frames

The source manifest records output/native-frame order, timestamp, source filename, source SHA-256, classification, and whether RGB or geometry may change. One-to-one records require `sourceFrameRequired: true`, `geometryChanged: false`, and no holds or interpolation.

Use `motionReferenceManifest` only for explicitly approved synthesized motion. It cannot satisfy source correspondence.

## Placement and visual fields

Record canvas, pivot, ground line, two-foot regions when relevant, visible bounds, locked and moving regions, required semantic regions, negative spaces, state templates, temporal limits, and numerical tolerances.

Temporal limits include global motion and seam ratios plus local alpha-silhouette change, visible-area step, bounding-box-size step and acceleration, and centroid step and acceleration. Approved motion transitions must be listed explicitly; do not relax a whole batch to accommodate one intentional movement.

Build the contract from the approved proof and source manifest. Run `validate_and_diagnose.py` for every frame, preserve failed frames and diagnostics, and use targeted repairs. Global metrics cannot authorize a pose that differs from its mapped source frame.
