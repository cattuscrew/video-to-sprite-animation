# GPT Image per-frame editing

Use the built-in GPT Image tool while keeping `frameConstruction: one-to-one-source`. Do not request an API key, call an external image API, or use browser/native-app computer control without the user's explicit approval for that specific action.

For output frame N, provide only its mapped selected video frame as the required pose input. A canonical character reference may be supplied only as a secondary appearance reference; it cannot replace the mapped frame or control its pose.

Do not start the batch until the user separately approves a canonical color-reference frame and color-consistency strategy. Transparency proof approval is not color-reference approval. Bind the approved reference by file path and SHA-256 and label it `role: appearance-only`.

For every GPT edit, the mapped native frame remains the primary pose input. When the image tool accepts multiple references, supply the approved color reference only as secondary appearance guidance and state that it controls palette/material appearance but not pose, silhouette, geometry, framing, scale, or equipment angle. If the user chooses deterministic palette normalization, apply it after all GPT edits and before frame/temporal validation while locking alpha and geometry.

## Required processing record

Record for every output:

- output frame and filename;
- selected native frame, timestamp, source filename, and source SHA-256;
- `classification: source-frame-gpt-edit`;
- `sourceFrameRequired: true`;
- `geometryChanged: false`;
- the GPT Image edit invocation or result identifier when available;
- output SHA-256 and source/output pose-review status.
- canonical color-reference path/SHA-256 and the approved color-consistency strategy.

Process all selected frames individually and in order. Do not generate one master and warp it, transfer centroid curves, reuse a nearby output, interpolate, or rebuild motion from tracked regions.

## Correspondence review

Create a full-resolution source/output comparison for every frame. Review silhouette, head and pelvis position, limb articulation, hair topology, eye state, overlaps, weapon/equipment angle, both boots, and all negative spaces. Record `reviewMethod: full-frame-source-output-comparison`. Each record must bind the native frame, source filename/SHA-256, output SHA-256, and `sourceOutputComparisonArtifact`; it must state `sourcePosePreserved`, `silhouettePreserved`, `topologyPreserved`, `equipmentGeometryPreserved`, `eyeStatePreserved`, `negativeSpacesPreserved`, `noSubstitutedPose`, and `noMasterWarp`.

GPT Image may change foreground pixels while cleaning the background. Pixel changes do not authorize pose changes. If an output no longer matches its mapped frame, repair that frame from the same source input or block it.

## GPT-only alpha repair

Use `processingMode: gpt-image-alpha-repair` only when the user wants to repair dirty transparency on an already approved one-to-one GPT sequence. Build `parent-frame-manifest.json` before generation. For output N:

- use approved parent frame N as the primary edit target;
- keep native source frame N as pose-verification authority, not as the edit target;
- keep the canonical color reference appearance-only;
- record the parent path/SHA-256 and native source path/SHA-256;
- request transparency and contaminated-edge cleanup only;
- reject changes to canvas, scale, placement, silhouette, outlines, interior RGB, topology, eyes, or equipment.

The parent must be an explicitly approved foreground result tied to the same native frame. A rejected proof, neighboring output, canonical master, or synthesized frame cannot be a parent. Validate each repair against both its parent and its native source. A clean alpha cannot waive parent-geometry or source-pose failure.

When the approved color strategy includes deterministic normalization, restore RGB from the approved parent only where both parent and repaired alpha are fully opaque. Preserve GPT alpha and edge RGB unchanged. This prevents interior color drift without becoming another background-removal method.
