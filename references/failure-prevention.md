# Failure prevention

Use this checklist to prevent clean-looking output from drifting away from the user’s source or intent.

## Require a background-tool decision

Before any background removal, ask the user to confirm exactly one tool: `rembg` or `GPT Image`. Do not infer the choice from “approve,” “remove the background,” or a prior unrelated experiment. There is no color-key, flood-fill, OpenCV keyer, or custom fallback in this workflow. If the selected tool is unavailable, stop and ask whether to switch explicitly.

`rembg` is the source-preserving branch: its alpha may be applied to the original native RGB, while generated RGB is discarded. `GPT Image` is the regenerative branch: changed geometry or RGB is expected and requires separate approval.

Approval is scoped. Record whether the user approved the source range, proof transparency, foreground appearance, regenerative redesign, motion strategy, and final sequence. Never infer approval for one scope from approval of another.

## Describe frames truthfully

Use one classification per delivered frame:

- `exact-source-extraction`: source RGB and geometry, alpha/background changes only;
- `source-derived-deformation`: source motion measurements applied to different pixels or geometry;
- `generated`: image-model output;
- `interpolated`: synthesized between authorities;
- `held/reused`: an earlier frame repeated.

Only the first classification may be called a frame extracted or picked from the source.

## Preserve native cadence

Write the output-to-native mapping before processing. At native FPS, use every mapped frame once. For lower FPS, record the explicit decimation list. When FPS changes, rebuild from the native mapping; do not double frames, interpolate the old output, or reuse a lower-FPS package without explicit authorization.

## Detect background failures where they occur

Inspect the complete outline plus named fragile regions: both sides under the chin, both armpits, hair/shoulder cavities, hands and weapon intersections, equipment boundaries, boots, and enclosed negative spaces. A single proof frame is not enough; inspect a numbered full-batch alpha/topology contact sheet and previous/current/next triplets. In the rembg branch, treat the mask as suspect until it passes fragile-region, outline, topology, and source-RGB checks. In the GPT Image branch, treat any local redraw, changed silhouette, or changed semantic feature as regeneration drift.

## Do not collapse source motion

Color centroids reduce a pose to translations and lose rotation, articulation, overlap, topology, and silhouette. Curve fitting can further suppress amplitude and shift phase; broad weighted warps can attenuate it again. Do not use centroid-only tracking, low-order smoothing, or one-master deformation when the source changes hair shape, limb relationships, equipment angles, or other topology. Exact-source requests use the source frames themselves.

For approved regeneration, validate dense landmarks or a constrained mesh against every mapped source frame. Measure amplitude ratio, trajectory correlation, phase, silhouette, topology, and equipment angle. If correspondence cannot be proved, label the result regenerative and blocked rather than source-faithful.

## Close the validation blind spot

Master consistency and temporal smoothness can approve a smooth but wrong animation. Native-source claims additionally require:

- a non-null per-frame authority;
- exact frame/timestamp mapping;
- `validate_source_correspondence.py` acceptance;
- no foreign/generated visible RGB in `rembg-extraction`;
- full alpha/outline and fragile-region checks;
- human inspection of normal and slow playback.

Do not mark a package accepted until every required gate passes.
