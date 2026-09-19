# Regenerative animation

Use this branch only when the user explicitly chooses `GPT Image` and accepts redraw risk. An approved canonical master is the design authority; the native video remains the motion authority. If the user chooses `rembg`, stay on the source-preserving branch and do not use these regeneration steps.

## Strategy order

Choose the first strategy that can preserve the requested motion:

1. **Deterministic canonical-master deformation.** Track the native source and deform one approved master with a mesh, bones, piecewise-affine motion, or optical flow constrained to named moving regions. Keep locked-region pixels and alpha unchanged.
2. **Layer compositing.** Create approved variants only for discrete states such as open/closed eyes, mouth shapes, or a hand overlap. Composite those layers onto deterministically deformed frames.
3. **Sparse generated key poses.** Generate only motion extrema that cannot be obtained by deformation, approve them, and interpolate between them with fixed topology and registration.
4. **Independent generated timeline frames.** Use only when the first three strategies are impossible and the user accepts redraw variation. Never use it by default for breathing, blinking, or other restrained idles.

Record the chosen strategy and why earlier strategies were unsuitable.

## Canonical layers and state control

Before building the timeline, classify every visible region as one of:

- `locked`: must retain canonical RGB and alpha;
- `deformed`: canonical pixels may move but must not be redrawn;
- `stateful`: may switch only among approved templates;
- `generated-key`: may come from an approved generated key pose.

For blinking, approve explicit eye-state templates. A model may create the templates, but timeline frames must composite one of those exact templates rather than regenerate eyes. Apply the same rule to mouth shapes, hand closures, and other discrete details. Temporal matching may allow only the small `maxTranslationPixels` window recorded in the contract for deterministic motion; it must not be used to excuse a changed feature.

Name fragile negative spaces, including gaps under hair, chin, arms, weapons, straps, and equipment. Record a transparent probe rectangle or mask for each. Validation must fail if those probes acquire opaque pixels or borrowed nearby colors.

## Motion transfer

Use the native source frames to estimate motion. Prefer landmarks, a constrained mesh, or region-limited flow over whole-image warping. Anchor the anatomical root, both foot contacts, and locked equipment attachment points. Apply one shared canvas transform before motion transfer; do not independently fit each output frame to its silhouette.

If flow crosses an occlusion or changes topology, split the subject into layers or add an approved key pose. Do not smear, dissolve, or cross-fade line art to hide a missing pose.

## Timeline acceptance

Run `scripts/validate_temporal_sequence.py` after per-frame validation. The timeline is not acceptable when any of these are true:

- unapproved duplicate or held frames exceed 10% of the timeline;
- more than one unapproved duplicate transition occurs consecutively;
- an adjacent-frame change spike is more than three times the median nonzero motion without an approved state transition;
- the loop seam exceeds three times the median nonzero motion;
- a locked region changes above its contract tolerance;
- a negative-space probe becomes occupied;
- a stateful region does not match an approved template;
- normal-speed or slow-speed review shows redraw shimmer, popping, stutter, or semantic drift.

Automatic mode may repair and revalidate, but it may not silently convert failures into holds. If a valid timeline cannot be built within the retry limit, keep the failed artifacts visible and mark the sequence blocked.

Intentional limited-animation holds are allowed when explicitly authored and recorded as approved hold transitions in the frame contract. They remain visible in the report but do not count as silent repair substitutions.
