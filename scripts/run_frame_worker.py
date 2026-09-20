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

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
GENERATED = CODEX_HOME / "generated_images"

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("frame", type=int)
    parser.add_argument("attempt", type=int)
    parser.add_argument("--brief-template", type=Path)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--codex", default="codex")
    args = parser.parse_args()

    job_directory = args.run / "jobs" / f"{args.frame:03d}"
    job = json.loads((job_directory / "job.json").read_text())
    directory = job_directory / f"attempt-{args.attempt:03d}"
    directory.mkdir(parents=True, exist_ok=True)

    # After the first moderation block, use the short prompt: on the 2026-09-20
    # run a shortened prompt rescued frames that a long one kept failing.
    previous = [
        json.loads(p.read_text())
        for p in sorted(job_directory.glob("attempt-*/record.json"))
    ]
    blocked_before = any(r.get("errorClass") == MODERATION for r in previous)
    prompt_path = args.run / ("prompt-short.txt" if blocked_before else "prompt.txt")
    if not prompt_path.is_file():
        prompt_path = args.run / "prompt.txt"
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

    command = [
        args.codex,
        "exec",
        "--json",
        "--skip-git-repo-check",
        # Not --ephemeral. The image tool resolves its referenced paths against
        # the session, and an ephemeral one has nothing to resolve against: it
        # rejects every absolute path with "AbsolutePathBuf deserialized without
        # a base path" and the turn then completes carrying that failure as
        # prose, so it reads as success unless the image is checked for.
        "-C",
        str(args.run.resolve()),
        "-s",
        "read-only",
        "-c",
        'approval_policy="never"',
        "-c",
        "features.default_mode_request_user_input=false",
        brief,
    ]
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
