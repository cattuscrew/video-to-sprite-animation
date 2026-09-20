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

Process all selected frames individually; execution order is free and frames may run concurrently. Each output is bound to its manifest index, never to its position in a directory listing. Do not generate one master and warp it, transfer centroid curves, reuse a nearby output, interpolate, or rebuild motion from tracked regions.

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

When the approved color strategy includes deterministic normalization, restore RGB from the approved parent only where both parent and repaired alpha are fully opaque. Preserve GPT alpha inside the parent's own support, and leave edge RGB unchanged. This prevents interior color drift without becoming another background-removal method.

Alpha repair may remove matte; it may never add it. Where the parent is not visible, the repaired output is made transparent and the clamped pixel count is recorded. Measured on the 2026-09-20 run, the tool grew the visible mask in every frame by up to 2.8% -- each one inside the 3% per-frame limit, and together enough to fail the sequence.

## Tool facts

The built-in image tool takes three arguments: a prompt, referenced image paths, and a count of recent images to include. There is no size, transparency, background, quality or output-path argument, so transparency must be requested in the prompt text. Never pass both referenced paths and a recent-image count.

- The returned canvas is not the canvas you supplied. A 720x720 input came back 1254x1254, so every output is resampled on the way back and internal outlines differ from the parent even when nothing was redrawn.
- The saved file lands in the session's own image directory, and the path is reported in prose rather than as a field. Bind it by the session id and the item id, never by "the newest file".
- Roughly two requests in five fail with an HTTP 400 `moderation_blocked` at the output stage on ordinary sprite art. It is not deterministic: the same prompt and input often pass on the next attempt, and a much shorter prompt helps. A block costs a full generation, so budget for it.
- Calls within one session are serialised by the host even when issued together, and a combined call discards its siblings' results when one fails. Issue one call per attempt with its own error handling, and get concurrency from separate worker processes instead.
- A usage-limit error ends the turn outright, with no closing message. Treat a turn that simply stops as a dead worker, not as a failed frame.
- Always record the tool's error text, including any request id. A driver that logs only "attempt failed" destroys the one piece of evidence that distinguishes a random block from a real defect.
