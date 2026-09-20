# Failure prevention

## Separate frame provenance from background removal

The selected video frames determine motion and pose. The fixed built-in GPT Image policy determines how each mapped frame is cleaned; it never changes frame provenance.

For one-to-one processing, build `source-frame-manifest.json` before any background work. Built-in GPT Image uses this manifest. Output N must use the exact source file and SHA-256 recorded for output N.

Use `motion-reference-manifest.json` only after explicit approval for synthesized motion. A frame used for centroids, landmarks, flow, interpolation, or master warping is merely a motion reference.

## Prevent source-frame substitution

Reject one-to-one delivery when any selected frame is skipped, duplicated, reordered, held, interpolated, or replaced. Reject a GPT sequence created from one master even if its movement was measured from every source frame. Smoothness and correct frame count do not establish correspondence.

Process every selected native frame individually with built-in GPT Image and review every source/output pair.

There is one link, not two: exact native source -> output. Editing from an approved earlier output was removed because it bound every RGB gate to a comparison between two outputs, so a defect the earlier one carried scored zero on all of them. Re-edit from the native frames instead.

## Fix the background tool and credential boundary

Use only the built-in GPT Image generation/editing tool. Do not offer rembg, chroma/color keying, flood-fill, OpenCV keying, a custom extractor, or an external image API. Never request or configure an API key. If the built-in tool is unavailable, stop and report the blocker without asking for credentials or silently changing methods.

Before invoking computer-use tooling to control any browser or native app, describe the specific action, ask for explicit approval, and wait. Keep that approval scoped to the named action; other workflow approvals do not authorize computer use.

Approval is scoped. Record source-range approval, the fixed built-in GPT Image policy, proof approval, accepted foreground-pixel policy, and whether synthesized motion is allowed. Proof transparency approval does not authorize master warping, pose replacement, external API access, or computer use.

## Ask one decision at a time

Before source processing, ask exactly one unresolved choice and wait. Do not combine FPS, canvas, loop, tool, proof, color reference, and batch authorization into one checklist or multi-question prompt. An answer approves only the named decision. Read-only skill loading and resolving the explicitly supplied input path are allowed before the first answer; source inspection, extraction, generation, and mutation are not.

For GPT Image, transparency proof, canonical color reference, color-consistency strategy, and batch execution are four separate gates. A generic “approve” applies only to the single question currently shown.

Any strategy change requires a new proof. Show source/output at full resolution, on black as well as on checkerboard, and reject any zoom, redraw, placement change, or canvas change before asking for batch approval.

## Prevent independent-frame color drift

Before a GPT Image batch, select and separately approve one canonical color reference. Store its path, SHA-256, and `role: appearance-only`; never use it as pose authority. Offer `reference-guided-gpt` and `reference-guided-gpt-with-deterministic-palette-normalization` as separate choices, recommending the latter when temporal color consistency matters. The deterministic pass may change foreground RGB only; it must preserve alpha, outlines, geometry, placement, and the exact source-frame mapping.

## Preserve cadence and fragile regions

At native FPS, use every mapped frame once. At lower FPS, record the explicit native-frame sampling list. When FPS changes, rebuild directly from native frames.

Inspect the full outline and named fragile regions: both sides under the chin, armpits, hair/shoulder gaps, hands and weapons, equipment boundaries, boots, and enclosed negative spaces. Inspect the complete numbered batch, not only one proof frame.

## Prevent late temporal failure

Per-frame limits and sequence limits fail differently, and a frame can pass every per-frame gate while making the sequence fail. On the 2026-09-20 run all 48 frames passed their per-frame gates, and the temporal gate then failed on two transitions and five accelerations, discovered at minute 100 of 103.

Two causes, both fixed without an image call:

- The repair grew the visible mask in every frame, by a median of 1.42% against a 3% per-frame limit. Area growth tracked centroid drift at 0.68. Clamping each output to its authority's support cleared five of the seven failures.
- The tool placed each sprite a fraction of a pixel away from its authority, by a median of 0.115px. Registering that offset out cleared three.

Neither was sufficient alone. Together they brought the sequence back to the authority's own level, with every frame within 0.074px of its authority.

Register in one resample. Shifting and then resizing softens the outline and leaves the sprite up to 0.2px from where it was asked to go -- most of a drift budget spent on arithmetic rather than on the image. Folding the shift into the resize as a source window is both sharper and about six times truer. It also reports slightly more drift on real frames, because the softer path was blurring the evidence away; that extra drift is signal.

Run the sequence gates as frames land, not once at the end.

## Close the validation blind spot

Final acceptance requires:

- immutable output/native-frame mapping with source SHA-256 values;
- complete source/output correspondence for every output;
- no skipped, duplicate, reordered, held, interpolated, or substituted frames;
- no master warp in one-to-one mode;
- frame, temporal, topology, outline, and fragile-region acceptance;
- `validate_delivery_package.py` acceptance.

Global bounds, pivot, palette, edge density, seam energy, or temporal smoothness cannot replace these checks.

Pass the frame manifest to the temporal validator. Given only a directory it cannot tell a missing frame from a shorter sequence, so it closes the gap and measures the frames either side as neighbours: a batch missing two frames reports as accepted, and the smoothest possible reading comes from the sequence that was never made.

## Prevent subtle independent-redraw jitter

Do not accept GPT frames from global motion energy alone. Use the contract's local silhouette-change, visible-area, bounding-box-size, centroid-step, and second-difference acceleration limits. Default motion-spike rejection is 2.0× median rather than the legacy 3.0× limit; local silhouette rejection is 1.8× median. Treat thresholds as rejection triggers, not proof of quality.

Inspect every triggered previous/current/next triplet and the complete alpha-onion sheet. Compare the suspected output with its exact mapped source before repair. Repair only the affected mapped frame from that source; keep the approved appearance reference secondary and do not substitute, warp, hold, or recenter another output. Re-run frame, source-correspondence, temporal, color, and delivery gates after repair.
