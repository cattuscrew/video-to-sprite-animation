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
7. **Choose the processing branch.** For faithful extraction, read and follow [faithful extraction](references/faithful-extraction.md). For regeneration, approve a canonical master and use [prompt templates](references/prompt-templates.md).
8. **Gate on one proof frame.** Before processing the batch, show one full-resolution proof on checkerboard, white, and black plus 100%/4× crops of fragile regions. Compare it with the native frame and canonical original. Record the approved shared extraction parameters; stop until approved.
9. **Build the frame contract.** Run `scripts/build_frame_contract.py` with the authority manifest. Read [frame contract](references/frame-contract.md). Include per-frame authority, protected/semantic regions, topology, outline, alpha, RGB, canvas, pivot, scale, and provenance requirements.
10. **Generate or process frames.** Use the same approved parameters for every faithful frame. Regenerative prompts must include contract values, locked/moving regions, and explicit bans on enlargement, recentering, cropping, recoloring, or outline redesign.
11. **Validate every frame with repair visibility.** Run `scripts/validate_and_diagnose.py`; in faithful extraction also run `scripts/validate_protected_frames.py` against the approved per-frame authorities. Require zero missing protected pixels, zero missing dark-outline pixels, zero new internal holes, zero protected RGB change, matching components, and required semantic-region coverage. Global bounds, pivot, palette, or edge density never substitute for these checks.
12. **Normalize and register safely.** Use one shared scale and integer translation. Do not independently recenter faithful source frames. Use `normalize_validate.py` for approved root registration only, never to conceal extraction or geometry drift.
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
- Canvas, camera, scale, ground line, and numerical pivot are shared.
- Prompt coordinates are advisory; enforce the contract deterministically.
- Validation must distinguish placement from missing parts, topology loss, outline damage, RGB mutation, and redraw wobble.
- A failed frame remains visible until repaired, explicitly blocked, or replaced by an explicitly valid recorded reuse.

## Deliverable summary

Report output directory, frame count, FPS/order, source range, pivot and maximum root deviation, authority provenance, proof-frame approval, processing mode/tool, missing protected/outline pixels, topology and semantic-region results, repairs, reused/held frames, blocked frames, and saved prompt set.
