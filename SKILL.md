---
name: video-to-sprite-animation
description: Convert character-animation video into stable transparent sprite frames with exact selected-video-frame mapping, user-confirmed rembg or GPT Image background removal, per-frame source correspondence, topology and outline checks, fixed-root registration, visible repair diagnostics, and resumable packaging. Use for video-to-sprite, idle-loop extraction, transparent frame animation, FPS conversion, or AI-assisted frame cleanup.
---

# Video to Sprite Animation

Run the workflow from one invocation while preserving the user’s selected source frames and tool choice. Never replace selected video frames with a processed master, reconstructed motion, or rejected artifact.

Read [failure prevention](references/failure-prevention.md) for background-method changes, GPT Image, FPS changes, source-frame claims, or repairs to a rejected sequence.

## Defaults

- Mode: `automatic` after the required source-preview and proof-frame approvals.
- Frame construction: `one-to-one-source`. Every output must derive from its corresponding selected video frame.
- Ask the user to confirm `rembg` or `GPT Image` before background removal. The tool choice is independent of frame mapping.
- Canvas: 512 × 512 unless specified otherwise; playback: 12 FPS unless source timing or the user specifies otherwise.
- Pivot: fixed anatomical bottom-center root; keep both boots on the shared ground line.
- Produce separate transparent PNGs, an exact-FPS MP4, and a looping GIF.
- There is no color-key, flood-fill, OpenCV keyer, custom mask, or silent fallback.

## Workflow

1. **Inspect the source.** Record native FPS, duration, resolution, and source usability. Render a representative contact sheet. Read [motion planning](references/motion-planning.md).
2. **Confirm selection settings.** Confirm the source range, native frame numbers, playback FPS, loop construction, canvas, and pivot. Do not infer a final range from a broad search range.
3. **Find the loop.** Extract and score candidates at native FPS with `scripts/find_loop_candidates.py`.
4. **Approve the source preview.** Show the proposed loop before background processing and stop until approved.
5. **Freeze the selected-frame map.** Decode the approved frames at native resolution. Run `scripts/build_source_frame_manifest.py` with the chosen background tool before processing. The manifest must list every output frame, native frame, timestamp, source filename, and source SHA-256.
6. **Confirm the background tool.** Ask the user to choose `rembg` or `GPT Image`. A generic “approve” is not tool approval. Record the choice and scoped proof approval in `authority-manifest.json`.
7. **Process one proof frame.** Show the full-resolution transparent proof on checkerboard, white, and black, plus 100%/4× fragile-region crops. Compare it with that exact mapped source frame. Stop until approved.
8. **Build the contract.** Run `scripts/build_frame_contract.py`. Read [frame contract](references/frame-contract.md).
9. **Process every mapped frame one-to-one.**
   - For rembg, read [rembg extraction](references/rembg-extraction.md). Apply the approved alpha to untouched source RGB.
   - For GPT Image, use each mapped native frame itself as that output’s edit input. Read [GPT per-frame editing](references/gpt-per-frame-editing.md) and [prompt templates](references/prompt-templates.md). Do not use one canonical master as the timeline source.
10. **Validate every output against its mapped source.** Run `scripts/validate_and_diagnose.py`, `scripts/validate_temporal_sequence.py`, and `scripts/validate_source_correspondence.py`. For rembg also run `scripts/validate_protected_frames.py`. For GPT Image, supply a complete pose-correspondence report comparing each output with its exact source frame.
11. **Normalize safely.** Use one shared scale and integer translation with `scripts/normalize_validate.py`. Per-frame recentering is off by default; never independently crop, enlarge, or recenter frames.
12. **Run visual QA.** Read [quality gates](references/quality-gates.md). Inspect source/output pairs, previous/current/next triplets, normal and slow playback, full-batch topology, checkerboard, white, and black views.
13. **Validate and package.** Create `delivery-report.json` with `selectedSourceFramesOneBased` exactly matching the source manifest. Run `scripts/validate_delivery_package.py`; package only when it returns accepted.

## Synthesized motion exception

Warping a master, transferring centroid/landmark/flow motion, generating new poses, interpolation, frame holds, or replacing a failed frame is not one-to-one processing. Use it only when the user explicitly approves synthesized motion. Then build `motion-reference-manifest.json` with `scripts/build_motion_reference_manifest.py`, classify outputs truthfully, and never report them as the selected video frames. Read [regenerative animation](references/regenerative-animation.md).

## Required invariants

- The approved source-frame list is immutable. At native FPS, use every selected frame exactly once and in order.
- For a selected range such as 154–201, output 1 derives from 154, output 2 from 155, through output 48 from 201.
- Background removal method and frame provenance are independent: both rembg and GPT Image may process one-to-one source frames.
- GPT Image one-to-one mode edits every selected source frame individually. It may change pixels, but it may not substitute pose, silhouette, timing, equipment angle, or another frame.
- No one-master warping, centroid transfer, motion reconstruction, interpolation, holding, skipping, duplication, or reordering is allowed unless the user explicitly approves synthesized motion.
- `source-frame-manifest.json` is mandatory for one-to-one processing regardless of background tool. Each record includes `sourceFrameRequired: true` and the source SHA-256.
- Validation must compare every output to the exact mapped source. Smoothness, pivot, palette, bounds, or master consistency cannot prove source correspondence.
- Changing FPS invalidates the timeline. Rebuild the mapping directly from native frames rather than reusing a prior lower-FPS output.
- Canvas, camera, shared scale, ground line, and numerical pivot remain fixed. Preserve the complete character and all equipment.
- Enclosed gaps under the chin, arms, hair, equipment, and other negative spaces stay transparent and cannot inherit neighboring colors.
- Failed frames remain visible until repaired or explicitly blocked; never silently substitute another frame.

## Deliverable summary

Report the output directory, frame count, FPS/order, exact selected native-frame list, source range, background tool, one-to-one classification, correspondence status, pivot/root deviation, topology and fragile-region results, repairs, blocked frames, and final delivery-gate status.
