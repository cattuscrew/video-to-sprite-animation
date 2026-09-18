# Faithful extraction

Use this branch when the video already contains usable artwork. The native video frame and any user-supplied clean original are the design and topology authorities.

## Authority manifest

Before extraction, write `authority-manifest.json` with:

- `sourceKind`: `canonical-original` or `native-source-derived`
- `canonicalMaster`: path to the clean original when available
- `nativeSource`: path to the video or decoded native frames
- `userApproved`: true only after proof-frame approval
- `derivedFromRejectedOutput`: false
- shared canvas, scale, integer translation, background-removal settings, and proof-frame identity

Validation must refuse missing, unapproved, rejected, or circular authority.

## Safe extraction order

1. Decode the approved pose at native video resolution.
2. Sample the matte from the outer border.
3. Seed background only from matte-like border pixels.
4. Grow background only through connected matte-like pixels. Similar-colored skin, collars, highlights, or antialiasing enclosed by the character remain foreground.
5. Preserve all residual foreground components. Unexpected components are a review failure, not permission to silently keep only the largest component.
6. Apply no erosion, silhouette closing, foreground feathering, nearest-interior RGB extension, or generative repainting.
7. Resize RGBA once with premultiplied-alpha resampling.
8. Apply one shared scale and integer translation. Do not independently recenter frames.

Use `scripts/extract_protected_foreground.py` for this branch.

## Forbidden failure-prone operations

- Global `distance from key color = foreground/background` classification without border connectivity
- RGB resizing before background removal
- Largest-component-only foreground selection
- Erosion of a line-art silhouette
- Edge cleanup that copies interior colors over outlines
- Bounding-box registration or non-uniform stretching of generated masks
- GPT-generated RGB or alpha controlling faithful production pixels
- Validation against a reference derived from the same rejected output

## Proof-frame gate

Process exactly one representative frame. Render black, white, and checkerboard views plus 100% and 4× crops of face/neck/collar, hair, hand/weapon, equipment edge, and boots. Compare against the native frame and canonical original. If thresholds need tuning, show a fixed sweep and choose one shared value. Do not process the batch until the user approves and the manifest records that approval.

## Required faithful checks

- zero missing protected pixels
- zero missing dark-outline pixels
- zero new internal alpha holes
- zero protected RGB error
- no missing or unexpected connected components
- required semantic regions present, especially any user-identified fragile regions
- exact shared scale/translation and pivot behavior
- no per-frame parameter tuning

High IoU, matching bounds, palette means, or edge density cannot waive these checks because small missing regions may leave global metrics nearly unchanged.
