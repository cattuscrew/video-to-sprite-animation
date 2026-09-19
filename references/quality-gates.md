# Quality gates

## Proof and source authority

Approve only when the character is complete, source-faithful, uncropped, consistently styled, genuinely transparent, and surrounded by enough padding for anticipated motion.

For one-to-one processing, each mapped native video frame remains pose authority. RemBG preserves its RGB; GPT Image may edit pixels but must preserve that frame's pose and structure. A canonical master cannot replace the per-frame source.

## Proof-frame gate

Before batch extraction or generation, inspect one representative proof frame on checkerboard, white, and black at 100% and 4×. Include fragile semantic crops such as face/neck/collar, hair tips, hands/weapons, equipment boundaries, and feet. Record the approved shared parameters in the authority manifest. Do not infer approval from a contact sheet viewed at reduced scale.

Record the scope of approval. Approval of transparency does not approve changed foreground RGB, changed geometry, regeneration, motion transfer, or a final sequence. A method or branch change requires a new proof.

## Per-frame rejection criteria

Reject or repair a frame when:

- dimensions or alpha mode differ
- stationary foot-contact y differs by more than 1 pixel after registration
- a locked landmark moves by more than 1 final pixel without planned motion
- character scale changes unexpectedly
- limb length, costume construction, or equipment dimensions drift
- camera, perspective, handedness, or line style changes
- the frame is cropped or independently recentered
- transparent edges show colored matte or halo
- a moving object takes an uneven angle or position step
- the drawing contains malformed anatomy or duplicated/missing parts
- any protected source pixel or dark-outline pixel is missing
- a new internal transparency hole appears
- a required semantic region such as neck or collar loses coverage
- protected RGB changes in `rembg-extraction`
- authority provenance is missing, circular, derived from rejected output, or not approved

## Sequence inspection

Inspect at normal speed, slow speed, and as previous/current/next triplets. Use:

- a fixed pivot crosshair
- checkerboard, white, and black backgrounds
- onion-skin overlays
- a numbered contact sheet
- playback with true frame durations and holds

Root alignment passing does not prove temporal consistency. Separately inspect head, pelvis, shoulders, hands, equipment centers, silhouette, and line-weight stability.

Run `scripts/validate_temporal_sequence.py` before acceptance. Inspect its duplicate-frame ratio, longest hold run, adjacent-motion spikes, loop-seam score, locked-region deltas, negative-space probes, and semantic-state matches. A sequence with excessive holds or redraw popping fails even when every still frame looks acceptable.

Run `scripts/validate_source_correspondence.py` for both tools. For rembg, require native visible-RGB identity. For GPT Image, require source SHA lineage and an accepted full-frame pose-correspondence record for every mapped source/output pair. Inspect silhouette, topology, equipment angles, motion phase, eye state, overlaps, and negative spaces.

For GPT per-frame editing, compare each output first with its exact mapped source and then with previous/current/next outputs. Treat changed pose, filled hair/shoulder gaps, changing eye construction, shifted equipment, or redrawn outlines as drift.

Bounds, pivot, palette mean, mask IoU, and aggregate edge density are supporting metrics only. They cannot accept a frame that fails protected-pixel, topology, outline, semantic-region, or provenance checks.

## Repair visibility

Never silently discard or silently substitute a failed frame. For every failed contract check:

- preserve the failed PNG;
- write the measured violation to `validation-report.json`;
- render a diagnostic overlay with the target pivot, actual pivot, visible bounds, and error labels;
- write one targeted repair prompt;
- retry at most twice;
- after repeated failure, mark the frame `user-visible-blocked` or record an explicitly justified hold/reuse.

The pivot contact sheet guides inspection and repair, but it is not a substitute for the canonical master or source-frame reference and should not be sent as the primary image-generation input.

## Required QA artifacts

The validation stage should produce `pivot-contact-sheet.png`, `white-contact-sheet.png`, `black-contact-sheet.png`, alpha-loss and topology diagnostics, 100%/4× fragile-region crops, an exact-FPS MP4 preview, a looping GIF, and a machine-readable validation report. The white and black sheets reveal complementary matte, halo, outline, and color errors.

## Final report

Record canvas, numerical pivot, frame count, unique/held/reused frames, FPS, playback order, measured pivot range, contract violations, diagnostic paths, repair prompts, validation warnings, retry count, and any intentional motion that exceeds generic thresholds.

Before packaging, run `validate_delivery_package.py`. One-to-one delivery must include accepted source correspondence and `selectedSourceFramesOneBased` exactly matching the manifest. A clean preview cannot override this truth gate.
