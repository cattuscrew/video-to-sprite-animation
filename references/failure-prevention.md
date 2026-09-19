# Failure prevention

## Separate frame provenance from background removal

The selected video frames determine motion and pose. The chosen background tool determines how each mapped frame is cleaned. Do not infer one from the other.

For one-to-one processing, build `source-frame-manifest.json` before any background work. Both rembg and GPT Image use this manifest. Output N must use the exact source file and SHA-256 recorded for output N.

Use `motion-reference-manifest.json` only after explicit approval for synthesized motion. A frame used for centroids, landmarks, flow, interpolation, or master warping is merely a motion reference.

## Prevent source-frame substitution

Reject one-to-one delivery when any selected frame is skipped, duplicated, reordered, held, interpolated, or replaced. Reject a GPT sequence created from one master even if its movement was measured from every source frame. Smoothness and correct frame count do not establish correspondence.

For GPT Image, process every selected native frame individually and review every source/output pair. For rembg, preserve native RGB and geometry and validate exact visible-pixel identity.

## Require a background-tool decision

Before background removal, ask the user to confirm `rembg` or `GPT Image`. Do not infer the choice from generic approval. If the selected tool is unavailable, stop; never substitute color-keying, flood-fill, OpenCV keying, or a custom extractor.

Approval is scoped. Record source-range approval, tool approval, proof approval, accepted foreground-pixel policy, and whether synthesized motion is allowed. Proof transparency approval does not authorize master warping or pose replacement.

## Preserve cadence and fragile regions

At native FPS, use every mapped frame once. At lower FPS, record the explicit native-frame sampling list. When FPS changes, rebuild directly from native frames.

Inspect the full outline and named fragile regions: both sides under the chin, armpits, hair/shoulder gaps, hands and weapons, equipment boundaries, boots, and enclosed negative spaces. Inspect the complete numbered batch, not only one proof frame.

## Close the validation blind spot

Final acceptance requires:

- immutable output/native-frame mapping with source SHA-256 values;
- complete source/output correspondence for every output;
- no skipped, duplicate, reordered, held, interpolated, or substituted frames;
- no master warp in one-to-one mode;
- frame, temporal, topology, outline, and fragile-region acceptance;
- `validate_delivery_package.py` acceptance.

Global bounds, pivot, palette, edge density, seam energy, or temporal smoothness cannot replace these checks.
