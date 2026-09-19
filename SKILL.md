---
name: video-to-sprite-animation
description: Convert character-animation video into stable transparent sprite frames with loop search, source and proof-frame approval gates, faithful native-resolution extraction or controlled regeneration, provenance-backed frame contracts, topology and outline validation, fixed-root registration, visible repair diagnostics, and resumable packaging. Use for video-to-sprite, frame animation, idle-loop extraction, rembg/color-key cutouts, or AI-generated animation frames.
---

# Video to Sprite Animation

Run the workflow from one invocation while preserving user choices. Do not ask the user to paste stage prompts. Never treat a processed or rejected artifact as design authority merely because it matches the desired canvas.

## Defaults

- Mode: `automatic` after required approval gates; use `review` for additional pauses when requested.
- Match the source style and preserve source pixels in faithful extraction.
- Produce separate transparent PNGs, not a generated sprite sheet.
- Canvas: 512 × 512 unless specified otherwise.
- Playback: 12 FPS unless source timing supports a better choice.
- Pivot: anatomical bottom-center root, fixed across frames.
- Choose `faithful-extraction` for usable source artwork and `regenerative` only when reconstruction or redesign is necessary.
- Save beside the source under `<video-stem>-sprites/` unless directed elsewhere.

## Workflow

1. **Preflight and inspect.** Run `ffprobe`, render a representative contact sheet, and record native FPS, duration, resolution, source usability, and any canonical original supplied by the user. Read [motion planning](references/motion-planning.md).
2. **Confirm selection settings.** Confirm source range, playback FPS, loop duration, natural versus ping-pong construction, canvas, and pivot. Do not invent a final one-second range from a broad search range.
3. **Search for loop candidates.** Extract at native FPS and run `scripts/find_loop_candidates.py`. Score natural windows and low-velocity half-cycles, including forward/reverse reuse for idle motion.
4. **Gate on source preview.** Show the candidate preview before background removal or generation. Record `selectionStatus: awaiting_user_approval`; stop until approved.
5. **Establish authority provenance.** Record the canonical original, native video, processing mode, and approval in `authority-manifest.json`. Authority must be `canonical-original` or `native-source-derived`, explicitly approved, and not derived from a rejected output. A processed result cannot validate itself.
6. **Extract approved frames at native resolution.** Preserve complete character, weapons, clothing, hair, face, neck, collar, hands, and feet. Do not resize, crop, recenter, or remove the background first.
7. **Choose the processing branch and animation strategy.** For faithful extraction, read and follow [faithful extraction](references/faithful-extraction.md). For regeneration, approve a canonical master, read [regenerative animation](references/regenerative-animation.md), and use [prompt templates](references/prompt-templates.md). Record whether motion will come from native-frame extraction, deterministic canonical-master deformation, sparse generated key poses, or independent generated frames. Independent per-frame generation is a last resort and is forbidden for subtle loops when deterministic motion transfer is possible.
8. **Gate on one proof frame.** Before processing the batch, show one full-resolution proof on checkerboard, white, and black plus 100%/4× crops of fragile regions. Compare it with the native frame and canonical original. Record the approved shared extraction parameters; stop until approved.
9. **Build the frame contract.** Run `scripts/build_frame_contract.py` with the authority manifest. Read [frame contract](references/frame-contract.md). Include per-frame authority, protected/semantic regions, topology, outline, alpha, RGB, canvas, pivot, scale, and provenance requirements.
10. **Generate or process frames.** Use the same approved parameters for every faithful frame. In regeneration, use GPT Image for the canonical master and a small approved set of semantic states or key poses, then derive timeline frames deterministically whenever practical. Do not ask an image model to redraw every frame of a restrained idle. Regenerative prompts must include contract values, locked/moving regions, and explicit bans on enlargement, recentering, cropping, recoloring, or outline redesign.
11. **Validate every frame and the timeline with repair visibility.** Run `scripts/validate_and_diagnose.py` and `scripts/validate_temporal_sequence.py`; in faithful extraction also run `scripts/validate_protected_frames.py` against the approved per-frame authorities. Require zero missing protected pixels, zero missing dark-outline pixels, zero new internal holes, zero protected RGB change, matching components, required semantic-region coverage, bounded adjacent-frame motion, and a clean loop seam. Track negative-space probes and discrete semantic states such as eyes or mouth when they can change. Stateful template matching may allow only the small `maxTranslationPixels` window recorded in the contract for deterministic motion; it must not excuse a changed feature. Global bounds, pivot, palette, edge density, or a contact sheet never substitute for these checks.
12. **Normalize and register safely.** Use one shared scale and integer translation derived from the approved master. Independent per-frame recentering is off by default in `normalize_validate.py` and requires explicit approval; never use it to conceal extraction, generation, or geometry drift.
13. **Run visual QA.** Read [quality gates](references/quality-gates.md). Produce checkerboard pivot, white, black, alpha-loss/topology diagnostics, exact-FPS MP4, looping GIF, and validation JSON. Inspect at normal speed, slow speed, 100%, 4×, and previous/current/next triplets.
14. **Package and report.** Package PNGs, metadata, authority manifest, frame contract, prompts, rejected artifacts, diagnostics, previews, and validation reports. Do not package a failed or circularly validated result as accepted.

## Mode behavior

### Automatic

Proceed automatically only after both source-selection and proof-frame approval. Exact range/FPS/canvas approval does not waive proof-frame approval for a new extraction or generation method.

### Review

Pause after the canonical master when applicable, after the proof frame, after key poses, and after final validation.

## Required invariants

- The canonical original/native source is authority in faithful extraction; the approved canonical master is authority in regeneration.
- Authority provenance is mandatory and cannot point to a rejected or derivative output.
- Background removal occurs at native resolution before scaling.
- In faithful extraction, never use global color similarity alone, largest-component deletion, silhouette erosion, foreground feathering, nearest-interior edge recoloring, or GPT-generated masks/RGB as production authority. Stabilize flood connectivity with a temporary dark-outline barrier that closes only tiny compression gaps; never apply that closing to the output silhouette.
- GPT Image may be diagnostic in faithful extraction; it may not subtract protected pixels, control geometry, or replace source RGB.
- GPT Image may establish an approved regenerative master or a small explicit set of semantic variants. It must not independently redraw every frame of a subtle idle when source-derived deformation, rigging, or layer compositing can supply the motion.
- Canvas, camera, scale, ground line, and numerical pivot are shared.
- Prompt coordinates are advisory; enforce the contract deterministically.
- Validation must distinguish placement from missing parts, topology loss, outline damage, RGB mutation, and redraw wobble.
- A final sequence fails when unapproved held or duplicate frames exceed 10% of the timeline, when more than one unapproved duplicate transition occurs consecutively, or when a frame-to-frame motion spike is unexplained by an approved semantic state change. Explicit authored holds may be recorded in the contract. Do not label a visibly laggy loop accepted because individual frames pass.
- Treat enclosed background gaps and other negative spaces as named contract regions. They must remain transparent and must not inherit nearby hair, skin, clothing, or outline colors.
- Eyes, mouth, hands, and other discrete semantic features use approved state templates or deterministic layers. Do not allow an image model to improvise their state independently per frame.
- State-template matching is locally registration-tolerant but bounded: record `maxTranslationPixels` per stateful region and keep it small enough that a shifted template cannot hide a changed feature.
- A failed frame remains visible until repaired, explicitly blocked, or replaced by an explicitly valid recorded reuse.

## Deliverable summary

Report output directory, frame count, FPS/order, source range, pivot and maximum root deviation, authority provenance, proof-frame approval, processing mode/tool, missing protected/outline pixels, topology and semantic-region results, repairs, reused/held frames, blocked frames, and saved prompt set.
