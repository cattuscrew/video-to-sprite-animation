---
name: video-to-sprite-animation
description: Convert character-animation video into stable transparent sprite frames with one-question-at-a-time approvals, exact selected-video-frame mapping, built-in GPT Image background removal and alpha-only repair, approved color authority, parent/source correspondence, fixed-root registration, visible diagnostics, and resumable packaging. Use for video-to-sprite, idle-loop extraction, transparent frame animation, FPS conversion, AI-assisted frame cleanup, or repairing dirty transparent edges in an approved sprite sequence.
---

# Video to Sprite Animation

Run the workflow from one invocation while preserving the user’s selected source frames and tool choice. Never replace selected video frames with a processed master, reconstructed motion, or rejected artifact.

Read [failure prevention](references/failure-prevention.md) for background-method changes, GPT Image, FPS changes, source-frame claims, or repairs to a rejected sequence.

## Defaults

- Mode: `automatic` only after the sequential decision gates, source-preview approval, transparency-proof approval, canonical color-reference approval for GPT Image, and final batch approval.
- Frame construction: `one-to-one-source`. Every output must derive from its corresponding selected video frame.
- Background removal is fixed to `GPT Image` through the built-in image-generation/editing tool. Do not offer a background-removal method choice.
- Canvas: 512 × 512 unless specified otherwise; playback: 12 FPS unless source timing or the user specifies otherwise.
- Pivot: fixed anatomical bottom-center root; keep both boots on the shared ground line.
- Produce separate transparent PNGs, an exact-FPS MP4, and a looping GIF.
- There is no rembg, color-key/chroma-key, flood-fill, OpenCV keyer, custom mask, external image API, or silent fallback.
- Never request, discover, read, or configure an API key. If the built-in GPT Image tool is unavailable, stop and report that the required tool is unavailable.
- Before any computer-use action that controls a browser or native app, ask for explicit approval for the specific proposed action and wait. Approval for image generation or batch execution does not approve computer use.
- Retry budgets are per frame and counted separately: output-stage moderation blocks (default 4, switching to the frozen short prompt after the first) and failed quality gates (default 2). A usage-limit error or a worker that dies spends neither; the run pauses and resumes from disk.
- The validation scripts need numpy and Pillow. Create the skill's own environment once with `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` and call them as `.venv/bin/python scripts/...`. Inside Codex, its bundled runtime Python at `~/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3` already has both; a bare `python3` does not.

## Execution modes

- `solo`: one agent runs every step, including the image calls. This is the default.
- `co-work`: an orchestrating agent runs every gate, manifest, registration and validator, and delegates only the image call, one frame per worker process, through `scripts/run_frame_worker.py` and [worker brief](references/worker-brief.md). The worker never copies, validates, selects, retries or judges its own output; attempts are reconstructed from the host's event stream, so a worker killed mid-turn still produces an honest record.

Both modes use the built-in image tool with no credentials, so `imageExecutionInterface` stays `built-in-image-tool` and `credentialMode` stays `none`. Record the mode as `executionMode` in the authority manifest and delivery report.

## Sequential decision gate

Before the first source-processing command, ask exactly one unresolved question with 2–3 concrete choices and wait for the answer. Continue one question per turn; never send a combined checklist, multi-question form, or treat one blanket “approve” as approval for several decisions. The only work allowed before the first answer is reading this skill and resolving the explicitly named input path.

Confirm these decisions separately before execution reaches work that depends on them: frame construction, playback FPS, and canvas/pivot policy. Background removal is not a choice: use built-in GPT Image only. After source inspection, separately approve the selected loop preview. After the proof is rendered, separately approve transparency/outline quality. Separately select and approve a canonical color-reference frame and color-consistency strategy. Finally, ask one batch-execution question summarizing the already approved settings. Record each answer and its scope; do not re-ask a choice the user explicitly answered.

Use a choice question even when recommending a default. Put the recommended option first and explain its consequence briefly. If a decision needs visual evidence, pause, create only that evidence, show it, then ask the single approval question.

These gates are separate because an answer's scope is exactly the question it was asked about. Merging them back into one checklist is how a transparency approval becomes read as permission to run a batch. Frame processing order is not one of these gates: frames are independent and may run in any order, or concurrently.

## Workflow

1. **Run sequential preflight.** Ask one choice at a time and wait after each answer. Confirm frame construction, FPS, and canvas/pivot policy before source processing. State that background removal uses built-in GPT Image; do not ask the user to choose a method. A generic “approve” cannot approve multiple decisions.
2. **Inspect the source.** Record native FPS, duration, resolution, and source usability. Render a representative contact sheet. Read [motion planning](references/motion-planning.md).
3. **Confirm selection settings sequentially.** Ask only the next unresolved choice. Confirm the source range/native frames and loop construction separately from any other setting. Do not infer a final range from a broad search range.
4. **Find the loop.** Extract and score candidates at native FPS with `scripts/find_loop_candidates.py`.
5. **Approve the source preview.** Show the proposed loop, ask only whether to approve that loop or inspect another candidate, and stop until answered.
6. **Freeze the selected-frame map.** Decode the approved frames at native resolution. Run `scripts/build_source_frame_manifest.py`; it records the fixed built-in GPT Image policy. The manifest must list every output frame, native frame, timestamp, source filename, and source SHA-256.
7. **Measure the authority's remaining temporal budget.** Run `scripts/preflight_parent_headroom.py` before any image call. Where an authority transition already sits near its own acceleration limit, no achievable per-frame accuracy keeps a repair inside it. Put those transitions to the user as one question: list them in `approvedTemporalTransitions` or choose a different authority. Never relax a limit for the whole batch to accommodate them.
8. **Process one transparency proof.** Show the full-resolution transparent proof on checkerboard, white, and black, plus 100%/4× fragile-region crops. Compare it with that exact mapped source frame. Ask one transparency/outline approval question and stop until answered.
   - For alpha-only repair of an already approved sequence, use the corresponding approved parent frame as the GPT edit target and the mapped native frame as pose-verification authority. Build `parent-frame-manifest.json` first with `scripts/build_parent_frame_manifest.py`. Show parent/output and source/output comparisons; do not batch until the repaired proof is approved.
9. **Approve color authority.** Show 2–3 color-reference choices when available: the approved proof/source frame, another selected native frame, or user-supplied clean artwork. Ask the user to select one, then show the chosen reference full-resolution and ask a separate approval question. Record its path, SHA-256, `role: appearance-only`, and approval in `authority-manifest.json`. Ask a separate question to choose `reference-guided-gpt` or `reference-guided-gpt-with-deterministic-palette-normalization`. A transparency approval is not color approval.
10. **Approve batch execution.** Summarize the already approved mapping, FPS, canvas/pivot, fixed built-in GPT Image policy, transparency proof, canonical color reference, and color strategy, and state both retry budgets and the two frozen prompt files. Ask one question: execute the mapped batch with those budgets, or revise one setting. Do not begin batch generation before approval. Freeze `prompt.txt` and `prompt-short.txt` at this point and record both SHA-256 values in the authority manifest.
11. **Build the contract.** Run `scripts/build_frame_contract.py`. Read [frame contract](references/frame-contract.md).
12. **Process every mapped frame one-to-one with built-in GPT Image.** Run `scripts/frame_jobs.py init`, then `run`. For initial extraction, use each mapped native frame itself as that output’s edit input. For approved alpha-only repair, use that output's SHA-bound approved parent frame as the edit target while retaining its mapped native frame as pose-verification authority. Read [GPT per-frame editing](references/gpt-per-frame-editing.md) and [prompt templates](references/prompt-templates.md). Frames are independent: execution order is free, and each output is bound to its manifest index, never to its position in a directory listing. Do not use one canonical master as the timeline source. Do not request an API key or switch to an external API.
13. **Register each attempt onto its own authority as it lands.** Run `scripts/register_to_authority.py` with `--lock-interior` for alpha repair. It undoes the sub-pixel offset the image tool introduces, removes matte invented outside the authority's outline, and restores approved interior RGB. Translation only, measured against that frame's own authority: this is not per-frame recentering, and an offset past the cap, a per-quadrant spread that indicates scale or warp, or a shrunken sprite is a rejection, not something to correct. If the approved color strategy includes palette normalization, apply it after per-frame editing and before validation, using the approved color reference for foreground RGB only. Never silently introduce recoloring when the user selected reference guidance only.
14. **Validate every output against its mapped source and color authority.** Render the per-frame comparisons with `scripts/build_pose_correspondence.py`, inspect them, and re-run it with `--accept <reviewer>` only for what you actually looked at; it fills the bindings and leaves every judgement false until then. Then run `scripts/validate_and_diagnose.py`, `scripts/validate_temporal_sequence.py` with `--frame-manifest` so a missing frame is named instead of letting the frames either side become neighbours, and `scripts/validate_source_correspondence.py`. For alpha repair also run `scripts/validate_alpha_repair.py` and supply `parent-frame-manifest.json`. Supply a complete pose-correspondence report comparing each output with its exact source frame; alpha repair records must additionally bind and compare the approved parent. Each record must accept silhouette, topology, equipment geometry, eye state, negative spaces, parent geometry, and parent foreground preservation and link both comparison artifacts. Inspect per-material color stability against the approved canonical reference.
15. **Normalize geometry safely.** Use one shared scale and integer translation with `scripts/normalize_validate.py`. Per-frame recentering is off by default; never independently crop, enlarge, or recenter frames. Registration onto a frame's own authority (step 13) is a different operation and is not affected by this: it is measured against that frame's approved parent or mapped source, never against a neighbour or a batch-wide average.
16. **Run visual QA.** Render the artifacts with `scripts/build_qa_artifacts.py`, then look at them. It writes `visual-qa-report.json` with every reviewed flag false; set them only for what you actually inspected. Read [quality gates](references/quality-gates.md). Inspect source/output pairs, previous/current/next triplets, normal and slow playback, the generated alpha-onion sheet, full-batch topology and landmark continuity, checkerboard, white, black, and color-reference comparison views. Write `visual-qa-report.json` using the required schema; a prose claim is insufficient.
17. **Validate and package.** Create `delivery-report.json` with `selectedSourceFramesOneBased` exactly matching the source manifest. Pass `visual-qa-report.json` to `scripts/validate_delivery_package.py`; package only when it returns accepted.

## Synthesized motion exception

Warping a master, transferring centroid/landmark/flow motion, generating new poses, interpolation, frame holds, or replacing a failed frame is not one-to-one processing. Use it only when the user explicitly approves synthesized motion. Then build `motion-reference-manifest.json` with `scripts/build_motion_reference_manifest.py`, classify outputs truthfully, and never report them as the selected video frames. Read [regenerative animation](references/regenerative-animation.md).

## Required invariants

- The approved source-frame list is immutable. At native FPS, use every selected frame exactly once and in order.
- For a selected range such as 154–201, output 1 derives from 154, output 2 from 155, through output 48 from 201.
- Background removal uses built-in GPT Image only; rembg and chroma-key extraction are not permitted workflow branches.
- GPT Image one-to-one mode edits every selected source frame individually. It may change pixels, but it may not substitute pose, silhouette, timing, equipment angle, or another frame.
- GPT Image alpha-repair mode may edit an approved parent frame only when `parent-frame-manifest.json` binds that parent to the exact native source frame and SHA-256. This is a repair lineage, not a new pose source.
- Alpha repair must preserve parent canvas, foreground geometry, placement, scale, outlines, and RGB appearance. Only transparency and contaminated edge pixels may change.
- GPT Image batch processing requires a separately user-approved canonical color reference with `role: appearance-only`. It guides palette and rendering only and never replaces the mapped native frame as pose authority.
- Transparency-proof approval and canonical color-reference approval are separate. Neither implies the other, and neither authorizes batch execution.
- No one-master warping, centroid transfer, motion reconstruction, interpolation, holding, skipping, duplication, or reordering is allowed unless the user explicitly approves synthesized motion.
- `source-frame-manifest.json` is mandatory for one-to-one processing. Each record includes `sourceFrameRequired: true` and the source SHA-256.
- Validation must compare every output to the exact mapped source. Smoothness, pivot, palette, bounds, or master consistency cannot prove source correspondence.
- Temporal acceptance must include local alpha-silhouette, visible-area, bounding-box-size, and centroid step/acceleration gates. A global motion average cannot waive a local redraw pop.
- Final delivery requires a machine-readable accepted visual-QA report covering normal speed, slow speed, triplets, onion skin, exact-source motion comparison, source/output pairs, topology, and named landmark continuity.
- Changing FPS invalidates the timeline. Rebuild the mapping directly from native frames rather than reusing a prior lower-FPS output.
- Canvas, camera, shared scale, ground line, and numerical pivot remain fixed. Preserve the complete character and all equipment.
- Enclosed gaps under the chin, arms, hair, equipment, and other negative spaces stay transparent and cannot inherit neighboring colors.
- Failed frames remain visible until repaired or explicitly blocked; never silently substitute another frame.

## Deliverable summary

Report the output directory, frame count, FPS/order, exact selected native-frame list, source range, background tool, one-to-one classification, correspondence status, pivot/root deviation, topology and fragile-region results, repairs, blocked frames, and final delivery-gate status.
