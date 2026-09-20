# GPT Image per-frame editing

Use the built-in GPT Image tool while keeping `frameConstruction: one-to-one-source`. Do not request an API key, call an external image API, or use browser/native-app computer control without the user's explicit approval for that specific action.

For output frame N, provide only its mapped selected video frame as the required pose input. A canonical character reference may be supplied only as a secondary appearance reference; it cannot replace the mapped frame or control its pose.

Do not start the batch until the user separately approves a canonical color-reference frame and color-consistency strategy. Transparency proof approval is not color-reference approval. Bind the approved reference by file path and SHA-256 and label it `role: appearance-only`.

For every GPT edit, the mapped native frame remains the primary pose input. When the image tool accepts multiple references, supply the approved color reference only as secondary appearance guidance and state that it controls palette/material appearance but not pose, silhouette, geometry, framing, scale, or equipment angle. If the user chooses deterministic palette normalization, apply it after all GPT edits and before frame/temporal validation while locking alpha and geometry.

## Required processing record

Record for every output:

- output frame and filename;
- selected native frame, timestamp, source filename, and source SHA-256;
- `classification: source-frame-gpt-edit`;
- `sourceFrameRequired: true`;
- `geometryChanged: false`;
- the GPT Image edit invocation or result identifier when available;
- output SHA-256 and source/output pose-review status.
- canonical color-reference path/SHA-256 and the approved color-consistency strategy.

Process all selected frames individually; execution order is free and frames may run concurrently. Each output is bound to its manifest index, never to its position in a directory listing. Do not generate one master and warp it, transfer centroid curves, reuse a nearby output, interpolate, or rebuild motion from tracked regions.

## Correspondence review

Create a full-resolution source/output comparison for every frame. Review silhouette, head and pelvis position, limb articulation, hair topology, eye state, overlaps, weapon/equipment angle, both boots, and all negative spaces. Record `reviewMethod: full-frame-source-output-comparison`. Each record must bind the native frame, source filename/SHA-256, output SHA-256, and `sourceOutputComparisonArtifact`; it must state `sourcePosePreserved`, `silhouettePreserved`, `topologyPreserved`, `equipmentGeometryPreserved`, `eyeStatePreserved`, `negativeSpacesPreserved`, `noSubstitutedPose`, and `noMasterWarp`.

GPT Image may change foreground pixels while cleaning the background. Pixel changes do not authorize pose changes. If an output no longer matches its mapped frame, repair that frame from the same source input or block it.

## One lineage

Every output is edited from its own mapped native frame. There is no parent
mode: a run that wants to fix an already delivered sequence re-edits from the
native frames, so no defect can be inherited from an earlier output.

That inheritance was the problem. Repairing from an approved parent bound every
RGB gate to a comparison between an output and another output, and a defect the
parent already carried scored zero on all of them. The 2026-09-20 sequence
passed every gate with a parent-inherited edge because nothing in the suite ever
compared a delivered frame with its own native source.

## Tool facts

The built-in image tool takes three arguments: a prompt, referenced image paths, and a count of recent images to include. There is no size, transparency, background, quality or output-path argument, so transparency must be requested in the prompt text. Never pass both referenced paths and a recent-image count.

- The returned canvas is not the canvas you supplied. A 720x720 input came back 1254x1254, so every output is resampled on the way back and internal outlines differ from the source even when nothing was redrawn.
- The soft edge it returns is straight-alpha and already unmixed: its partial-alpha pixels hold the artwork's own colour, not the background's. On the reference source only 0.65-1.5% of edge pixels were background-coloured. Unmixing the whole edge against the screen colour drives a dark keyline's green negative and leaves a magenta fringe -- worse than what it set out to fix. Measure before treating an edge.
- About a third of edits come back re-illustrated rather than cut out. Measured
  over 120 attempts on a 48-frame batch: 25% accepted, 40% moderation-blocked,
  35% rejected for geometry. The rejected ones are internally clean sprites --
  correct pose, correct colours, no halo -- but the character is drawn 17% to
  34% larger than it is in its own source frame, with a per-quadrant shift
  spread of 1.5 to 2.5px against 0.14px for accepted ones. The separation is
  total: no rejected frame overlaps the accepted range on either measure.
  Nothing that looks at a frame on its own can see this, because the frame is
  self-consistent; only measuring it against its own source can. Asking the
  prompt not to enlarge does not prevent it -- retry and reject does.
- Even an accepted frame is redrawn, not cut out. The linework is re-rendered
  every time and lands a fraction of a pixel differently: between neighbouring
  delivered frames 2.29% of interior pixels swung over 40 luma levels, and
  those pixels sat on the artwork's lines at 66 times the local gradient of the
  flat areas. It reads as shimmer on every outline, eye, seam and rivet. It is
  not colour, so no colour gate or colour pass touches it, and no threshold
  reaches it. The remedy is to stop using the tool's drawing where the source
  has one, keeping only its alpha.
- Because of that rate, a frame needs about four attempts on average. Retry
  budgets of 4 safety / 2 quality blocked a third of a batch on the quality
  budget alone while the frames themselves were fine.
- The 429 usage-limit body carries `resets_at` as an epoch integer. The prose
  form ("try again at 6:20 PM") appears only in some messages, so parse both or
  the queue knows it is paused without knowing until when.
- The saved file lands in the session's own image directory, and the path is reported in prose rather than as a field. Bind it by the session id and the item id, never by "the newest file".
- Roughly two requests in five fail with an HTTP 400 `moderation_blocked` at the output stage on ordinary sprite art. It is not deterministic: the same prompt and input often pass on the next attempt, and a much shorter prompt helps. A block costs a full generation, so budget for it.
- Calls within one session are serialised by the host even when issued together, and a combined call discards its siblings' results when one fails. Issue one call per attempt with its own error handling, and get concurrency from separate worker processes instead.
- A usage-limit error ends the turn outright, with no closing message. Treat a turn that simply stops as a dead worker, not as a failed frame.
- Always record the tool's error text, including any request id. A driver that logs only "attempt failed" destroys the one piece of evidence that distinguishes a random block from a real defect.

## Headless workers

`codex exec --json` runs a worker without a terminal and prints one JSON object per line. The events that matter:

- `thread.started` carries `thread_id`, which names the session's own image directory under `$CODEX_HOME/generated_images/`. Bind each image by that id plus the item id; never take "the newest file".
- `turn.completed` is the only evidence a turn finished. A turn that stops after `turn.started` did not finish, and that is what a usage limit looks like from outside.
- `turn.failed` carries the error message, including the usage-limit text and its "try again at" time, which is machine-readable enough to pause a queue on.

Do not pass `--ephemeral`: the image tool resolves its referenced paths against the session, and an ephemeral one has nothing to resolve against, so it rejects every absolute path with `AbsolutePathBuf deserialized without a base path`. The turn then completes carrying that failure as an ordinary message, so it reads as success unless the image itself is checked for. Flags a worker needs: `--skip-git-repo-check`, `-C <run directory>`, `-s read-only`, `-c approval_policy="never"`, and `-c features.default_mode_request_user_input=false`, which is what stops a worker blocking on a question nobody will answer. Close its stdin. Unset `OPENAI_API_KEY` and `CODEX_API_KEY` so `credentialMode` stays honest. Give it a wall-clock kill: a worker that hangs is not a frame that failed.

Measured on 2026-09-20: a headless worker generated in 58 seconds, and one frame in a two-frame batch was moderation-blocked and passed on the following attempt with the short prompt -- the same roughly two-in-five rate seen in the desktop run.

Concurrency belongs between worker processes, never inside one. Whether separate processes generate in parallel is a property of the account, so raise it from one only on measured evidence, and remember that quota, not wall-clock, was the binding constraint on 2026-09-20.
