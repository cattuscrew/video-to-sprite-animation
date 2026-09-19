# Frame contract

The frame contract is the machine-readable authority for consistency after source selection.

## Required fields

- `processingMode`: `faithful-extraction` or `regenerative`
- `authority`: manifest path, source kind, canonical/native paths, approval, and rejected-output provenance
- `canvas`: final width and height
- `pivot`: numerical root in top-left coordinates
- `pivotMeasurement`: lowest-contact or two-foot anatomical measurement with explicit foot regions; use two-foot measurement for uneven stances
- `groundY`: boot-contact ground line
- `visibleBounds` and `visibleSize`: approved character envelope
- `lockedRegions`: regions that must not be redrawn or drift
- `requiredSemanticRegions`: named regions such as neck/collar with minimum alpha/outline coverage
- `allowedMovingRegions`: regions allowed to change for the pose
- `negativeSpaceRegions`: regions or masks that must stay transparent
- `statefulRegions`: discrete features with approved templates, such as open and closed eyes; set `maxTranslationPixels` to the small deterministic motion allowance used for matching
- `temporalLimits`: maximum duplicate ratio, consecutive holds, adjacent-motion spike ratio, and loop-seam ratio
- `tolerances`: numerical limits for pivot, scale, palette, edge density, and margins

Faithful extraction additionally requires a per-frame authority directory and exact limits for missing protected pixels, missing dark-outline pixels, new internal holes, protected RGB error, component-count changes, and per-frame parameter drift.

## How to use it

1. Build it from an approved native-source proof frame in faithful extraction or the approved canonical master in regeneration. Never build it from rejected or circular derivative output.
2. Include the contract values in generation prompts as constraints.
3. Run `validate_and_diagnose.py` after every generated or processed frame.
4. Preserve the failed frame and diagnostic overlay when a constraint fails.
5. Write one targeted repair prompt rather than accumulating generic negative prompts.

The contract is not a replacement for visual review. It prevents measurable drift while the pivot, white, black, and checkerboard contact sheets expose defects that need human inspection.

Global metrics cannot authorize missing parts. A faithful frame fails if any protected/topology/semantic check fails even when its pivot, bounds, palette mean, edge density, or mask IoU passes.
