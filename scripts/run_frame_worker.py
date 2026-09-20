#!/usr/bin/env python3
"""Run one Codex worker for one frame attempt.

The worker's only job is to call the built-in image tool and let the image land
in its own session directory. It does not copy, resize, validate, select, or
read any other frame; this script does the copying, and the gates run
afterwards, so a worker cannot talk its own output into the sequence.

Attempts are reconstructed from the host-written event stream rather than from
anything the worker says about itself. A usage-limit error kills the turn
outright -- that is how the 2026-09-20 run ended, with no closing message -- so
a worker that dies mid-sentence still produces an honest record here.

Standard library only: this runs inside the frame_jobs driver, which has no
numpy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

MODERATION = "moderation_blocked"
USAGE_LIMIT = "usage_limit_reached"
WORKER_DIED = "worker_died"
TOOL_ERROR = "tool_error"
NONE = "none"

# The worker pins these instead of inheriting them. Without -m and the two
# overrides it runs on whatever ~/.codex/config.toml happens to say, so
# switching model or effort in the TUI silently changes what a half-finished
# batch is generated with, and nothing in the record says which.
DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_EFFORT = "medium"
# Fast mode is the priority service tier: 1.5x speed, and it spends usage
# faster, which matters on a run that has hit the limit before.
STANDARD_TIER = "default"
FAST_TIER = "priority"

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
GENERATED = CODEX_HOME / "generated_images"
MODEL_CATALOG = CODEX_HOME / "models_cache.json"

# The tool reports a rejected generation as an HTTP 400 carrying this code; it
# is an output-stage moderation block, fires on roughly two requests in five,
# and says nothing about the frame.
MODERATION_PATTERN = re.compile(r"moderation_blocked|safety system", re.I)
USAGE_PATTERN = re.compile(r"usage limit|usage_limit_reached|rate.?limit", re.I)
RESETS_PATTERN = re.compile(r"try again at ([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM)?)", re.I)
# The 429 body carries the reset as an epoch: {"error":{...,"resets_at":1758...}}.
# Without this the queue knows it is paused but not until when, and has to be
# restarted by hand instead of waiting the right amount of time.
RESETS_EPOCH_PATTERN = re.compile(r'"resets_at"\s*:\s*([0-9]{10,13})')
IMAGE_ID_PATTERN = re.compile(r"(exec-[0-9a-f-]{36})")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_brief(job: dict, prompt: str, template: str) -> str:
    # Image 1 is always the frame's own mapped native source. Image 2, when the
    # run approved one, is the colour reference -- appearance only, never a
    # second pose source. A reference recorded in the manifest but never sent
    # guides nothing, which is how a whole batch once drifted in colour.
    inputs = [job["authority"]]
    if job.get("colorReference"):
        inputs.append(job["colorReference"])
    paths = "\n".join(
        f"  Image {n}: {path}" for n, path in enumerate(inputs, start=1)
    )
    if len(inputs) > 1:
        paths += (
            "\n\nImage 2 is the approved colour reference, and it is "
            "appearance only: use it to keep palette and material colours "
            "consistent with the rest of the batch. It is not a pose, "
            "silhouette, geometry, scale or framing source."
        )
    return template.format(
        output_frame=job["outputFrame"],
        native_frame=job.get("nativeFrame"),
        image_paths=paths,
        image_count=len(inputs),
        prompt=prompt,
    )


def choose_prompt(run: Path) -> Path:
    """The short prompt, on every attempt, whenever the run froze one.

    It used to be held back until a frame had been blocked once, on the
    reading that a shorter prompt talked the safety system round. Measured
    across the 167 real calls of the 2026-09-20 run, it does not: moderation
    fires on 41% of short-prompt calls against 42% of long-prompt ones, and
    the block is independent of the frame as well -- a frame blocked on its
    first attempt is blocked on later ones 37% of the time, against 40% for a
    frame that was not.

    What the short prompt actually does is stop the tool re-illustrating.
    Quality rejections run 28% against 40%, and acceptance 31% against 18%,
    on a comparison biased against it: it only ever ran on frames that had
    already failed. Holding it back spent the long prompt's worse odds on
    every frame's first attempt.
    """
    short = run / "prompt-short.txt"
    return short if short.is_file() else run / "prompt.txt"


def parse_events(path: Path) -> dict:
    """Pull thread id, image ids and failures out of the host's event stream."""
    found = {
        "threadId": None,
        "itemIds": [],
        "errors": [],
        "turnFailed": None,
        "completed": False,
    }
    if not path.is_file():
        return found
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type") or event.get("msg", {}).get("type")
        if kind == "thread.started":
            found["threadId"] = event.get("thread_id")
        elif kind == "error":
            found["errors"].append(str(event.get("message", "")))
        elif kind == "turn.failed":
            found["turnFailed"] = str(event.get("error", {}).get("message", ""))
        elif kind == "turn.completed":
            found["completed"] = True
        # Image items are reported with an id that is also the filename stem.
        blob = json.dumps(event)
        for match in IMAGE_ID_PATTERN.findall(blob):
            if match not in found["itemIds"]:
                found["itemIds"].append(match)
    return found


def classify(found: dict, stdout: str, stderr: str) -> tuple[str, str]:
    text = "\n".join(found["errors"] + [found["turnFailed"] or "", stdout, stderr])
    if USAGE_PATTERN.search(text):
        return USAGE_LIMIT, text.strip()[-2000:]
    if MODERATION_PATTERN.search(text):
        return MODERATION, text.strip()[-2000:]
    if found["turnFailed"]:
        return TOOL_ERROR, found["turnFailed"][-2000:]
    if not found["completed"]:
        return WORKER_DIED, (text.strip() or "worker produced no final message")[-2000:]
    return TOOL_ERROR, text.strip()[-2000:]


def resets_at(text: str) -> float | None:
    """When the limit lifts, so the queue can wait rather than be restarted.

    Two forms, because the tool uses both: an epoch in the 429 body, and prose
    in the message a worker relays.
    """
    epoch = RESETS_EPOCH_PATTERN.search(text or "")
    if epoch:
        value = int(epoch.group(1))
        # Milliseconds if it is too large to be seconds.
        return value / 1000.0 if value > 10_000_000_000 else float(value)
    match = RESETS_PATTERN.search(text or "")
    if not match:
        return None
    raw = match.group(1).strip().upper().replace(" ", "")
    for fmt in ("%I:%M%p", "%H:%M"):
        try:
            parsed = time.strptime(raw, fmt)
        except ValueError:
            continue
        now = time.localtime()
        target = time.struct_time(
            (now.tm_year, now.tm_mon, now.tm_mday, parsed.tm_hour, parsed.tm_min, 0, 0, 0, -1)
        )
        stamp = time.mktime(target)
        return stamp + 86400 if stamp <= time.time() else stamp
    return None


def newest_image(thread_id: str | None, item_ids: list[str], since: float) -> Path | None:
    """The image this attempt produced, bound to its own session directory."""
    directories = []
    if thread_id and (GENERATED / thread_id).is_dir():
        directories.append(GENERATED / thread_id)
    elif GENERATED.is_dir():
        directories.extend(p for p in GENERATED.iterdir() if p.is_dir())
    for item in item_ids:
        for directory in directories:
            candidate = directory / f"{item}.png"
            if candidate.is_file():
                return candidate
    # No item id in the stream: fall back to this session's newest file, and
    # only one written after the attempt began.
    newest, newest_time = None, since
    for directory in directories:
        for candidate in directory.glob("*.png"):
            stamp = candidate.stat().st_mtime
            if stamp > newest_time:
                newest, newest_time = candidate, stamp
    return newest


def validate_settings(
    model: str, effort: str, fast: bool, catalog_path: Path = MODEL_CATALOG
) -> list[str]:
    """Reject settings the local catalog says cannot work.

    `codex exec` takes a misspelled `-c model_reasoning_effort=` without
    complaint, so a typo does not fail: it runs the batch at some other effort
    and the record then attests to a setting that was never applied. Checked
    before the queue starts, because the alternative is one dead worker per
    frame until the attempt budget runs out. An unreadable catalog validates
    nothing rather than blocking the run: it is a cache, not an authority.
    """
    try:
        catalog = json.loads(catalog_path.read_text())
    except (OSError, ValueError):
        return []
    models = {entry.get("slug"): entry for entry in catalog.get("models", [])}
    if not models:
        return []
    if model not in models:
        return [f"unknown model {model!r}; the catalog lists {', '.join(sorted(models))}"]
    entry = models[model]
    errors = []
    # Presence, not truthiness: an empty list is the catalog saying "none",
    # while a missing key is it saying nothing, and only the first is a
    # rejection.
    if "supported_reasoning_levels" in entry:
        efforts = [
            level.get("effort") for level in entry["supported_reasoning_levels"]
        ]
        if effort not in efforts:
            errors.append(
                f"{model} does not support reasoning effort {effort!r}; "
                f"it supports {', '.join(e for e in efforts if e) or 'none'}"
            )
    if fast and "service_tiers" in entry:
        tiers = [tier.get("id") for tier in entry["service_tiers"]]
        if FAST_TIER not in tiers:
            errors.append(f"{model} has no {FAST_TIER} service tier, so Fast mode is unavailable")
    return errors


def build_command(
    codex: str, run: Path, brief: str, model: str, effort: str, tier: str
) -> list[str]:
    """The exec invocation for one attempt, with the model settings pinned."""
    return [
        codex,
        "exec",
        "--json",
        "--skip-git-repo-check",
        # Not --ephemeral. The image tool resolves its referenced paths against
        # the session, and an ephemeral one has nothing to resolve against: it
        # rejects every absolute path with "AbsolutePathBuf deserialized without
        # a base path" and the turn then completes carrying that failure as
        # prose, so it reads as success unless the image is checked for.
        "-C",
        str(run.resolve()),
        "-s",
        "read-only",
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{effort}"',
        "-c",
        f'service_tier="{tier}"',
        "-c",
        'approval_policy="never"',
        "-c",
        "features.default_mode_request_user_input=false",
        brief,
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("frame", type=int)
    parser.add_argument("attempt", type=int)
    parser.add_argument("--brief-template", type=Path)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="codex exec -m")
    parser.add_argument(
        "--reasoning-effort",
        default=DEFAULT_EFFORT,
        help="low, medium, high or xhigh; whatever this codex build accepts",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help=f"run on the {FAST_TIER} service tier (Fast mode) instead of {STANDARD_TIER}",
    )
    args = parser.parse_args()

    job_directory = args.run / "jobs" / f"{args.frame:03d}"
    job = json.loads((job_directory / "job.json").read_text())
    directory = job_directory / f"attempt-{args.attempt:03d}"
    directory.mkdir(parents=True, exist_ok=True)

    prompt_path = choose_prompt(args.run)
    prompt = prompt_path.read_text()

    template_path = args.brief_template or (
        Path(__file__).resolve().parent.parent / "references" / "worker-brief.md"
    )
    brief = build_brief(job, prompt, template_path.read_text())
    (directory / "brief.txt").write_text(brief)

    events_path = directory / "worker-events.jsonl"
    started = time.time()

    environment = dict(os.environ)
    # The tool must stay the built-in one; credentialMode is recorded as none.
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "ANTHROPIC_API_KEY"):
        environment.pop(key, None)

    problems = validate_settings(args.model, args.reasoning_effort, args.fast)
    if problems:
        raise SystemExit("; ".join(problems))
    tier = FAST_TIER if args.fast else STANDARD_TIER
    command = build_command(args.codex, args.run, brief, args.model, args.reasoning_effort, tier)
    timed_out = False
    try:
        with open(events_path, "w") as stream:
            process = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.PIPE,
                text=True,
                timeout=args.timeout,
                env=environment,
            )
        stderr = process.stderr or ""
    except subprocess.TimeoutExpired as expired:
        timed_out = True
        stderr = (expired.stderr or b"").decode(errors="replace") if isinstance(expired.stderr, bytes) else (expired.stderr or "")

    found = parse_events(events_path)
    record: dict[str, object] = {
        "outputFrame": args.frame,
        "attempt": args.attempt,
        "threadId": found["threadId"],
        "promptUsed": prompt_path.name,
        "promptSha256": sha256(prompt_path),
        "startedAt": started,
        "finishedAt": time.time(),
        "imageExecutionInterface": "built-in-image-tool",
        "credentialMode": "none",
        "model": args.model,
        "reasoningEffort": args.reasoning_effort,
        "serviceTier": tier,
    }

    image = None if timed_out else newest_image(found["threadId"], found["itemIds"], started)
    if image is not None:
        raw = directory / "raw.png"
        shutil.copyfile(image, raw)
        record.update(
            {
                "status": "accepted",
                "errorClass": NONE,
                "itemId": image.stem,
                "generatedImage": str(image),
                "outputSha256": sha256(raw),
                "inputSha256": {
                    "authority": sha256(Path(job["authority"])),
                },
            }
        )
    else:
        if timed_out:
            error_class, error_text = WORKER_DIED, f"worker exceeded {args.timeout}s"
        else:
            error_class, error_text = classify(found, "", stderr)
        record.update(
            {
                "status": "repair-needed",
                "errorClass": error_class,
                "errorText": error_text,
            }
        )
        if error_class == USAGE_LIMIT:
            stamp = resets_at(error_text)
            if stamp:
                record["resetsAt"] = stamp
                record["resetsAtIso"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%S", time.localtime(stamp)
                )

    (directory / "record.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({k: record[k] for k in ("outputFrame", "attempt", "status", "errorClass")}))
    return 0 if record["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
