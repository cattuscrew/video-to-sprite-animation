# GPT Image per-frame editing

Use this branch after the user confirms GPT Image while keeping `frameConstruction: one-to-one-source`.

For output frame N, provide only its mapped selected video frame as the required pose input. A canonical character reference may be supplied only as a secondary appearance reference; it cannot replace the mapped frame or control its pose.

## Required processing record

Record for every output:

- output frame and filename;
- selected native frame, timestamp, source filename, and source SHA-256;
- `classification: source-frame-gpt-edit`;
- `sourceFrameRequired: true`;
- `geometryChanged: false`;
- the GPT Image edit invocation or result identifier when available;
- output SHA-256 and source/output pose-review status.

Process all selected frames individually and in order. Do not generate one master and warp it, transfer centroid curves, reuse a nearby output, interpolate, or rebuild motion from tracked regions.

## Correspondence review

Create a full-resolution source/output comparison for every frame. Review silhouette, head and pelvis position, limb articulation, hair topology, eye state, overlaps, weapon/equipment angle, both boots, and all negative spaces. Record `reviewMethod: full-frame-source-output-comparison`. Each record must bind the native frame, source filename/SHA-256, and output SHA-256 and state `sourcePosePreserved`, `noSubstitutedPose`, and `noMasterWarp`.

GPT Image may change foreground pixels while cleaning the background. Pixel changes do not authorize pose changes. If an output no longer matches its mapped frame, repair that frame from the same source input or block it.
