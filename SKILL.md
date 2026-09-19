---
name: video-to-sprite-animation
description: Convert character-animation video into stable transparent sprite frames with exact native-frame mapping, source and proof approval gates, mandatory background-tool confirmation (`rembg` or `GPT Image`), source-correspondence validation, topology and outline checks, fixed-root registration, visible repair diagnostics, and resumable packaging. Use this skill for video-to-sprite, frame animation, idle-loop extraction, rembg/GPT Image cutouts, FPS conversion, or AI-generated animation frames.
---

# Video to Sprite Animation

Run the workflow from one invocation while preserving user choices. Do not ask the user to paste stage prompts. Never treat a processed or rejected artifact as design authority merely because it matches the desired canvas.

Read [failure prevention](references/failure-prevention.md) whenever the request involves background-method changes, GPT Image, FPS changes, source-frame claims, or repair of a previously rejected sequence.

## Defaults

- Mode: `automatic` after required approval gates; use `review` for additional pauses when requested.
- Ask the user to confirm `rembg` or `GPT Image` before any background removal. Never select a background-removal method silently.
- Use the rembg branch when source RGB and geometry must remain authoritative. Use GPT Image only when the user explicitly accepts regeneration and possible source-pixel changes.
- Produce separate transparent PNGs, not a generated sprite sheet.
- Canvas: 512 × 512 unless specified otherwise.
- Playback: 12 FPS unless source timing supports a better choice.
- Pivot: anatomical bottom-center root, fixed across frames.
- Processing modes are `rembg-extraction` and `gpt-image-regeneration`. There is no built-in color-key, flood-fill, OpenCV keyer, or custom background-removal fallback.
- Save beside the source under `<video-stem>-sprites/` unless directed elsewhere.

## Workflow

1. **Preflight and inspect.** Run `ffprobe`, render a representative contact sheet, and record native FPS, duration, resolution, source usability, and any canonical original supplied by the user. Read [motion planning](references/motion-planning.md).
2. **Confirm selection settings.** Confirm source range, playback FPS, loop duration, natural versus ping-pong construction, canvas, and pivot. Do not invent a final one-second range from a broad search range.
3. **Search for loop candidates.** Extract at native FPS and run `scripts/find_loop_candidates.py`. Score natural windows and low-velocity half-cycles, including forward/reverse reuse for idle motion.
4. **Gate on source preview.** Show the candidate preview before background removal or generation. Record `selectionStatus: awaiting_user_approval`; stop until approved.
5. **Establish authority provenance and exact mapping.** Record the canonical original, native video, processing mode, and approval in `authority-manifest.json`. For source-derived work, run `scripts/build_source_frame_manifest.py` before processing so every output maps to one native frame and timestamp. Authority must be `canonical-original` or `native-source-derived`, explicitly approved, and not derived from a rejected output. A processed result cannot validate itself.
6. **Extract approved frames at native resolution.** Preserve complete character, weapons, clothing, hair, face, neck, collar, hands, and feet. Do not resize, crop, recenter, or remove the background first.
7. **Require explicit background-tool confirmation before processing.** Ask the user to choose exactly one method: `rembg` or `GPT Image`. Record `backgroundRemovalTool`, `backgroundRemovalToolApproved`, and the selected processing mode in the authority manifest. A generic “approve” is not method approval. If the user has not chosen, stop. If the selected tool is unavailable, report the blocker; never fall back to an unapproved keyer, mask, or extractor.
8. **Apply the approved branch.** For `rembg-extraction`, read [rembg extraction](references/rembg-extraction.md), run rembg at native resolution, and apply only its approved alpha to the original source RGB; rembg-generated RGB is not production authority. For `gpt-image-regeneration`, separately approve a canonical regenerated master and accept loss of exact source pixels; read [regenerative animation](references/regenerative-animation.md) and [prompt templates](references/prompt-templates.md). Do not use image generation to redraw every frame of a restrained idle.
9. **Gate on one proof frame with scoped approval.** Before processing the batch, show one full-resolution proof on checkerboard, white, and black plus 100%/4× crops of fragile regions. Compare it with the exact mapped native frame. Record precisely what was approved: selected tool, source range, extraction/regeneration branch, foreground RGB policy, geometry, and motion strategy. Approval of clean transparency does not approve the other tool or branch; stop until the required scope is approved.
10. **Build the frame contract.** Run `scripts/build_frame_contract.py` with the authority manifest. Read [frame contract](references/frame-contract.md). Include per-frame authority, protected/semantic regions, topology, outline, alpha, RGB, canvas, pivot, scale, and provenance requirements.
11. **Generate or process frames.** Use one approved rembg configuration for every rembg frame, preserving source RGB and geometry. In GPT Image mode, use GPT Image for the canonical master and a small approved set of semantic states or key poses, then derive timeline frames deterministically whenever practical. Regenerative prompts must include contract values, locked/moving regions, and explicit bans on enlargement, recentering, cropping, recoloring, or outline redesign.
12. **Validate every frame, its source correspondence, and the timeline.** Run `scripts/validate_and_diagnose.py` and `scripts/validate_temporal_sequence.py`; in rembg extraction also run `scripts/validate_protected_frames.py` and `scripts/validate_source_correspondence.py`. Require the selected tool to match the authority manifest, exact native-frame identity for rembg, zero foreign/generated visible RGB in rembg, zero missing protected or dark-outline pixels, zero new holes, matching components, required semantic-region coverage, bounded adjacent motion, and a clean seam. A native-motion claim cannot pass with missing per-frame authority. Global bounds, smoothness, pivot, palette, edge density, or contact sheets never substitute for source correspondence.
13. **Normalize and register safely.** Use one shared scale and integer translation derived from the approved master. Independent per-frame recentering is off by default in `normalize_validate.py` and requires explicit approval; never use it to conceal extraction, generation, or geometry drift.
14. **Run visual QA.** Read [quality gates](references/quality-gates.md). Produce checkerboard pivot, white, black, alpha-loss/topology diagnostics, exact-FPS MP4, looping GIF, and validation JSON. Inspect at normal speed, slow speed, 100%, 4×, and previous/current/next triplets.
15. **Package and report truthfully.** Classify every frame as `exact-source-extraction`, `source-derived-deformation`, `generated`, `interpolated`, or `held/reused`. Package PNGs, source mapping, metadata, authority manifest, frame contract, prompts, rejected artifacts, diagnostics, previews, and all validation reports. Do not call a deformation or redraw a “source frame.” Do not package a failed, source-inaccurate, or circularly validated result as accepted.

## Mode behavior

### Automatic

Proceed automatically only after both source-selection and proof-frame approval. Exact range/FPS/canvas approval does not waive proof-frame approval for a new extraction or generation method.

### Review

Pause after the canonical master when applicable, after the proof frame, after key poses, and after final validation.

## Required invariants

- The canonical original/native source is authority in `rembg-extraction`; the approved canonical master is authority in `gpt-image-regeneration`.
- There are exactly two supported background-removal paths: user-approved rembg or user-approved GPT Image. No color-key, flood-fill, OpenCV keyer, custom mask, or other unapproved extractor may run in this workflow.
- Tool choice and approval are explicit authority fields. A generic approval never authorizes switching tools or branches.
- A proof approval is scoped. Transparency approval alone does not approve foreground redraw, geometry change, motion transfer, or the full sequence.
- Authority provenance is mandatory and cannot point to a rejected or derivative output.
- Exact-source work requires a complete output-to-native-frame/timestamp manifest and source-correspondence report.
- Background removal occurs at native resolution before scaling.
- In `rembg-extraction`, never use global color similarity, largest-component deletion, silhouette erosion, foreground feathering, nearest-interior edge recoloring, GPT-generated masks, or GPT-generated RGB as production authority. Use rembg's approved alpha with the untouched native RGB, then validate fragile regions and source correspondence.
- GPT Image is a separate regenerative branch, not a diagnostic substitute for rembg. It may not be used in the rembg branch to subtract protected pixels, control geometry, or replace source RGB.
- GPT Image may establish an approved regenerative master or a small explicit set of semantic variants. It must not independently redraw every frame of a subtle idle when source-derived deformation, rigging, or layer compositing can supply the motion.
- Canvas, camera, scale, ground line, and numerical pivot are shared.
- Prompt coordinates are advisory; enforce the contract deterministically.
- Validation must distinguish placement from missing parts, topology loss, outline damage, RGB mutation, and redraw wobble.
- Centroid-only motion tracking, low-order curve fitting, and one-master warping are insufficient when source silhouettes, hair topology, limb relationships, or equipment angles change. Reject them for exact-source requests.
- Changing playback FPS invalidates the prior timeline. Rebuild from the native-frame manifest; never silently duplicate, interpolate, or reuse a lower-FPS result.
- A final sequence fails when unapproved held or duplicate frames exceed 10% of the timeline, when more than one unapproved duplicate transition occurs consecutively, or when a frame-to-frame motion spike is unexplained by an approved semantic state change. Explicit authored holds may be recorded in the contract. Do not label a visibly laggy loop accepted because individual frames pass.
- Treat enclosed background gaps and other negative spaces as named contract regions. They must remain transparent and must not inherit nearby hair, skin, clothing, or outline colors. A full-batch alpha/topology contact sheet must prove that the selected tool did not erase or fill artwork.
- Eyes, mouth, hands, and other discrete semantic features use approved state templates or deterministic layers. Do not allow an image model to improvise their state independently per frame.
- State-template matching is locally registration-tolerant but bounded: record `maxTranslationPixels` per stateful region and keep it small enough that a shifted template cannot hide a changed feature.
- A failed frame remains visible until repaired, explicitly blocked, or replaced by an explicitly valid recorded reuse.
- Final acceptance requires frame, temporal, source-correspondence, alpha/outline, provenance, and required human visual gates. Smooth but source-inaccurate output fails.

## Deliverable summary

Report output directory, frame count, FPS/order, exact output-to-native mapping, source range, pivot and maximum root deviation, authority provenance, scoped proof approval, processing classification/tool, source-correspondence status, missing protected/outline pixels, topology and semantic-region results, repairs, reused/held/generated/interpolated frames, blocked frames, and saved prompt set.
