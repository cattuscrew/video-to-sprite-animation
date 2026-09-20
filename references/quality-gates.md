# Quality gates

## Proof and source authority

Approve only when the character is complete, source-faithful, uncropped, consistently styled, genuinely transparent, and surrounded by enough padding for anticipated motion.

For one-to-one processing, each mapped native video frame remains pose authority. Built-in GPT Image may edit pixels but must preserve that frame's pose and structure. A canonical master cannot replace the per-frame source.

## Proof-frame gate

Before batch extraction or generation, inspect one representative proof frame on checkerboard, white, and black at 100% and 4×. Include fragile semantic crops such as face/neck/collar, hair tips, hands/weapons, equipment boundaries, and feet. Record the approved shared parameters in the authority manifest. Do not infer approval from a contact sheet viewed at reduced scale.

Record the scope of approval. Approval of transparency does not approve changed foreground RGB, changed geometry, regeneration, motion transfer, or a final sequence. A method or branch change requires a new proof.

For GPT Image, show and approve a canonical color reference after transparency approval and before batch execution. This is a separate gate. Record the reference path/SHA-256, `role: appearance-only`, approved strategy, and explicit batch approval. Reject a batch whose authority record lacks any of these fields.

## Per-frame rejection criteria

Reject or repair a frame when:

- dimensions or alpha mode differ
- stationary foot-contact y differs by more than 1 pixel after registration
- a locked landmark moves by more than 1 final pixel without planned motion
- character scale changes unexpectedly
- limb length, costume construction, or equipment dimensions drift
- camera, perspective, handedness, or line style changes
- hair, skin, fabric, leather, wood, or metal colors visibly change between adjacent frames without source-authorized lighting change
- the frame is cropped or independently recentered
- transparent edges show colored matte or halo
- a moving object takes an uneven angle or position step
- the drawing contains malformed anatomy or duplicated/missing parts
- any protected source pixel or dark-outline pixel is missing
- a new internal transparency hole appears
- a required semantic region such as neck or collar loses coverage
- authority provenance is missing, circular, derived from rejected output, or not approved

## Sequence inspection

Motion checks need motion. Watching the exact-FPS preview is the direct way; where that is not possible, per-transition analysis is the substitute: a hitch is a transition whose motion collapses toward zero, a jump is one that separates, and both are visible in a silhouette differenced against the frame before it. Record which was done in `motionReviewMethod`, because "reviewed" without a method is the claim this gate exists to stop.

Prefer MP4 for both previews. GIF frame delays are whole centiseconds, so 24fps becomes 25 and an "exact FPS" preview is not exact.

Render the artifacts before judging: `scripts/build_qa_artifacts.py` writes the exact-FPS preview, the slowed preview, triplets for the flagged frames, a whole-batch onion sheet, and per-frame comparisons against the mapped native frame. It also decodes the preview back and compares it with the frame it claims to show, because a lossy encode rings around a sprite edge and the ringing reads as a contaminated matte. It sets every reviewed flag false, because rendering a picture is not the same as having seen it. A reviewer sets them; the delivery gate then checks each named artifact exists.

Inspect at normal speed, slow speed, and as previous/current/next triplets. Use:

- a fixed pivot crosshair
- checkerboard, white, and black backgrounds
- onion-skin overlays
- a numbered contact sheet
- playback with true frame durations and holds

Root alignment passing does not prove temporal consistency. Separately inspect head, pelvis, shoulders, hands, equipment centers, silhouette, and line-weight stability.

Run `scripts/validate_temporal_sequence.py` before acceptance. Inspect its duplicate-frame ratio, longest hold run, adjacent-motion spikes, loop-seam score, locked-region deltas, negative-space probes, and semantic-state matches. A sequence with excessive holds or redraw popping fails even when every still frame looks acceptable.

Also inspect its local geometry metrics. Reject an unapproved transition or one-frame pulse that exceeds the contract's silhouette-change, visible-area, bounding-box-size, centroid-step, or acceleration limits. These limits are deliberately stricter than the legacy global-motion gate: a short redraw pop cannot pass merely because it remains below three times median motion. Review every generated flagged triplet and the complete alpha-onion sheet.

Run `scripts/validate_source_correspondence.py`. Require source SHA lineage and an accepted full-frame pose-correspondence record for every mapped source/output pair. Inspect silhouette, topology, equipment angles, motion phase, eye state, overlaps, and negative spaces.

For GPT per-frame editing, compare each output first with its exact mapped source and then with previous/current/next outputs. Treat changed pose, filled hair/shoulder gaps, changing eye construction, shifted equipment, or redrawn outlines as drift.

Compare in this order: exact source/output for pose correspondence, then previous/current/next outputs for temporal stability. Reject canvas-size changes, zoom, recentering, foreground redraw, material-color changes, or line changes even if the new alpha looks cleaner.

The per-frame gate compares the opaque interior with the native source on three measures: mean absolute RGB error, signed per-channel bias, and the fraction of the interior that is dark linework. Bias is the sensitive one -- on the reference run local resampling moved the mean by 9 levels while bias never exceeded 3.8, so a tint shift shows there first.

Judge a transparent edge on black, not only on the checkerboard. A coloured or ragged rim is close to invisible against a mid-tone check pattern. Judge it on a lossless preview too: a defect the encoder invented is indistinguishable from one the image tool did.

Prepare the review with `scripts/build_pose_correspondence.py`. It renders a full-resolution comparison per frame and fills in the native frame, both digests and the artifact link; it leaves every judgement false. Whether a silhouette survived, whether the eyes are still two dots, whether the sword sits at the same angle -- no checksum sees any of that, which is why the gate asks a reviewer. Accepting a review of 46 frames does not accept 48: a missing frame keeps the report pending.

The GPT pose-correspondence record for every frame must explicitly accept silhouette, topology, equipment geometry, eye state, and negative spaces, and link the rendered full-frame source/output comparison used for that judgment. A generic `sourcePosePreserved` boolean is insufficient.

Also compare stable material regions against the approved canonical color reference. Record per-region robust color statistics for hair, skin, primary garment, leather, wood, and metal when present. Aggregate palette means alone are insufficient: reject visible regional hue/value flicker even when the global mean passes.

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

It must also produce a slow preview, flagged previous/current/next triplets, `temporal-alpha-onion-sheet.png`, an exact-source/output motion comparison, and `visual-qa-report.json`. The visual-QA report has `status: accepted`, a `reviewer` of `agent`, `user`, or `agent-and-user`, existing artifact paths, and true values for `normalSpeedReviewed`, `slowSpeedReviewed`, `tripletsReviewed`, `onionSkinReviewed`, `sourceOutputPairsReviewed`, `sourceMotionCompared`, and `topologyAndLandmarksReviewed`. The delivery validator blocks a missing, incomplete, or dangling report.

## Final report

Record canvas, numerical pivot, frame count, unique/held/reused frames, FPS, playback order, measured pivot range, contract violations, diagnostic paths, repair prompts, validation warnings, retry count, and any intentional motion that exceeds generic thresholds.

Before packaging, run `validate_delivery_package.py`. One-to-one delivery must include accepted source correspondence and `selectedSourceFramesOneBased` exactly matching the manifest. A clean preview cannot override this truth gate.
