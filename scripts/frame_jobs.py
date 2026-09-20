#!/usr/bin/env python3
"""Per-frame job queue for image-tool batches.

Each mapped output frame is one job with its own directory, its own attempts
and its own record. Nothing is derived from listing a directory: the manifest
is the only source of which frames exist, so a frame that never lands stays
visible as a hole rather than letting its neighbours shuffle into its place.

Two retry budgets, because the two failure modes are unrelated. The image tool
rejects roughly two in five requests at random through output-stage moderation,
which says nothing about the frame; a failed quality gate says everything about
it. A usage-limit error is neither, and consumes no budget -- the run pauses and
resumes from disk.

Standard library only, so the queue can be inspected without the venv.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ACCEPTED = "accepted"
REPAIR_NEEDED = "repair-needed"
BLOCKED = "user-visible-blocked"

# Error classes. Only the first two draw on a budget.
MODERATION = "moderation_blocked"
QUALITY = "quality_failed"
USAGE_LIMIT = "usage_limit_reached"
WORKER_DIED = "worker_died"
TOOL_ERROR = "tool_error"

DEFAULT_BUDGETS = {"safetyBlock": 4, "quality": 2}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def jobs_dir(run: Path) -> Path:
    return run / "jobs"


def job_dir(run: Path, frame: int) -> Path:
    return jobs_dir(run) / f"{frame:03d}"


def attempt_dirs(run: Path, frame: int) -> list[Path]:
    root = job_dir(run, frame)
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("attempt-*") if p.is_dir())


def attempt_records(run: Path, frame: int) -> list[dict]:
    records = []
    for path in attempt_dirs(run, frame):
        record_path = path / "record.json"
        if record_path.is_file():
            record = read_json(record_path)
            record.setdefault("attempt", int(path.name.split("-")[1]))
            records.append(record)
    return records


def budgets(run: Path) -> dict[str, int]:
    """Retry budgets, as approved at batch execution."""
    authority = run / "authority-manifest.json"
    if authority.is_file():
        approved = read_json(authority).get("approvalScope", {}).get("retryBudgets")
        if isinstance(approved, dict):
            return {**DEFAULT_BUDGETS, **{k: int(v) for k, v in approved.items()}}
    return dict(DEFAULT_BUDGETS)


def spent(records: list[dict]) -> dict[str, int]:
    return {
        # A tool error is transient enough to retry and expensive enough to
        # bound: counted here, a broken request stops after four attempts
        # instead of looping until someone notices.
        "safetyBlock": sum(
            1 for r in records if r.get("errorClass") in (MODERATION, TOOL_ERROR)
        ),
        "quality": sum(1 for r in records if r.get("errorClass") == QUALITY),
    }


def selected_attempt(run: Path, frame: int) -> dict | None:
    path = job_dir(run, frame) / "selected.json"
    return read_json(path) if path.is_file() else None


def pause_until(run: Path) -> float | None:
    """The latest usage-limit reset time across all unresolved jobs."""
    resets = []
    for job in sorted(jobs_dir(run).glob("*/job.json")) if jobs_dir(run).is_dir() else []:
        frame = int(job.parent.name)
        if selected_attempt(run, frame):
            continue
        for record in attempt_records(run, frame):
            if record.get("errorClass") == USAGE_LIMIT and record.get("resetsAt"):
                resets.append(float(record["resetsAt"]))
    return max(resets) if resets else None


def resolve_source_directory(
    manifest: dict, manifest_path: Path, override: Path | None = None
) -> Path:
    """Where the native frames live.

    A manifest may name each source file but keep the directory in another
    manifest it points at. Read only the first and every job gets a bare
    filename, which the image tool rejects outright.
    """
    if override:
        return override
    direct = manifest.get("sourceFramesDirectory")
    if direct and Path(direct).is_dir():
        return Path(direct)
    linked = manifest.get("sourceFrameManifest")
    if linked:
        path = Path(linked)
        if not path.is_absolute():
            path = manifest_path.parent / path
        if path.is_file():
            nested = read_json(path).get("sourceFramesDirectory")
            if nested and Path(nested).is_dir():
                return Path(nested)
    return Path("")


# --------------------------------------------------------------------------- init


def cmd_init(args: argparse.Namespace) -> int:
    manifest = read_json(args.manifest)
    mapping = manifest.get("frameMapping", [])
    if not mapping:
        raise SystemExit("manifest has no frameMapping")

    mode = manifest.get("processingMode") or "gpt-image-per-frame-edit"
    source_dir = resolve_source_directory(manifest, args.manifest, args.source_frames)

    created = 0
    for record in mapping:
        frame = int(record["outputFrame"])
        directory = job_dir(args.run, frame)
        job_path = directory / "job.json"
        if job_path.is_file() and not args.force:
            continue
        job = {
            "outputFrame": frame,
            "outputFile": record.get("outputFile", f"frame-{frame:03d}.png"),
            "nativeFrame": record.get("nativeFrame"),
            "processingMode": mode,
            "sourceFile": str(source_dir / str(record["sourceFile"])) if record.get("sourceFile") else None,
            "sourceSha256": record.get("sourceSha256"),
        }
        # The mapped native frame is both the edit target and the authority:
        # there is no second lineage to confuse it with.
        job["editTarget"] = "source"
        job["authority"] = job["sourceFile"]
        if args.prompt:
            job["promptSha256"] = sha256(args.prompt)
        if args.short_prompt:
            job["shortPromptSha256"] = sha256(args.short_prompt)
        if args.color_reference:
            job["colorReference"] = str(args.color_reference)
            job["colorReferenceSha256"] = sha256(args.color_reference)
        unresolved = [
            f"{key}={job[key]}"
            for key in ("authority", "sourceFile")
            if job.get(key) and not Path(job[key]).is_file()
        ]
        if unresolved:
            raise SystemExit(
                f"frame {frame}: job inputs do not resolve to files on disk: "
                f"{', '.join(unresolved)}. A worker cannot open these, and the "
                "image tool rejects a path it cannot resolve."
            )
        write_json(job_path, job)
        created += 1

    print(json.dumps({"jobs": len(mapping), "created": created, "run": str(args.run)}, indent=2))
    return 0


# --------------------------------------------------------------------------- next


def pending_frames(run: Path, limits: dict[str, int]) -> tuple[list[dict], list[dict]]:
    """Returns (ready, exhausted)."""
    ready, exhausted = [], []
    for job_path in sorted(jobs_dir(run).glob("*/job.json")):
        frame = int(job_path.parent.name)
        if selected_attempt(run, frame):
            continue
        records = attempt_records(run, frame)
        used = spent(records)
        item = {
            "outputFrame": frame,
            "attemptsMade": len(records),
            "spent": used,
            "nextAttempt": len(records) + 1,
            "job": str(job_path),
        }
        over = [k for k in ("safetyBlock", "quality") if used[k] >= limits[k]]
        if over:
            item["exhausted"] = over
            exhausted.append(item)
        else:
            ready.append(item)
    # Fewest attempts first, so one frame that keeps failing cannot hold up
    # every frame behind it while it spends its budget.
    ready.sort(key=lambda item: (item["attemptsMade"], item["outputFrame"]))
    return ready, exhausted


def cmd_next(args: argparse.Namespace) -> int:
    limits = budgets(args.run)
    ready, exhausted = pending_frames(args.run, limits)
    paused = pause_until(args.run)
    payload = {
        "budgets": limits,
        "ready": ready[: args.limit] if args.limit else ready,
        "readyCount": len(ready),
        "exhaustedCount": len(exhausted),
        "exhausted": exhausted,
    }
    if paused and paused > time.time():
        payload["pausedUntil"] = paused
        payload["pausedUntilIso"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(paused))
    print(json.dumps(payload, indent=2))
    return 0


# --------------------------------------------------------------------------- select


def cmd_select(args: argparse.Namespace) -> int:
    frame, attempt = args.frame, args.attempt
    directory = job_dir(args.run, frame) / f"attempt-{attempt:03d}"
    locked = directory / "locked.png"
    registered = directory / "registered.png"
    chosen = locked if locked.is_file() else registered
    if not chosen.is_file():
        raise SystemExit(f"frame {frame} attempt {attempt}: no locked.png or registered.png")

    job = read_json(job_dir(args.run, frame) / "job.json")
    destination = args.run / "frames" / job["outputFile"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(chosen, destination)

    record = attempt_records(args.run, frame)
    item_id = next(
        (r.get("itemId") for r in record if r.get("attempt") == attempt and r.get("itemId")),
        None,
    )
    write_json(
        job_dir(args.run, frame) / "selected.json",
        {
            "outputFrame": frame,
            "attempt": attempt,
            "source": str(chosen),
            "itemId": item_id,
            "outputSha256": sha256(destination),
            "selectedAt": time.time(),
        },
    )
    print(json.dumps({"outputFrame": frame, "attempt": attempt, "frame": str(destination)}, indent=2))
    return 0


# --------------------------------------------------------------------------- status


def cmd_status(args: argparse.Namespace) -> int:
    limits = budgets(args.run)
    frames: list[dict] = []
    ledger: dict[str, int] = {}
    duplicate_items: list[dict] = []

    for job_path in sorted(jobs_dir(args.run).glob("*/job.json")):
        frame = int(job_path.parent.name)
        job = read_json(job_path)
        records = attempt_records(args.run, frame)
        chosen = selected_attempt(args.run, frame)
        used = spent(records)

        for record in records:
            item = record.get("itemId")
            if not item:
                continue
            if item in ledger and ledger[item] != frame:
                duplicate_items.append({"itemId": item, "frames": [ledger[item], frame]})
            ledger[item] = frame

        if chosen:
            status = ACCEPTED
        elif any(r.get("errorClass") == USAGE_LIMIT for r in records):
            status = REPAIR_NEEDED
        elif any(used[k] >= limits[k] for k in limits):
            status = BLOCKED
        else:
            status = REPAIR_NEEDED

        last = records[-1] if records else {}
        frames.append(
            {
                "outputFrame": frame,
                "nativeFrame": job.get("nativeFrame"),
                "status": status,
                "attempts": len(records),
                "spent": used,
                "selectedAttempt": chosen.get("attempt") if chosen else None,
                "lastErrorClass": last.get("errorClass"),
                "lastError": last.get("errorText"),
            }
        )

    paused = pause_until(args.run)
    errors: list[str] = []
    for item in duplicate_items:
        errors.append(
            f"image item {item['itemId']} claimed by frames {item['frames']}"
        )
    for entry in frames:
        if entry["status"] == BLOCKED:
            errors.append(f"frame {entry['outputFrame']}: retry budget exhausted")

    accepted = sum(1 for f in frames if f["status"] == ACCEPTED)
    if paused and paused > time.time():
        overall = "paused"
    elif accepted == len(frames) and frames:
        overall = ACCEPTED
    elif any(f["status"] == BLOCKED for f in frames):
        overall = BLOCKED
    else:
        overall = REPAIR_NEEDED

    report = {
        "status": overall,
        "run": str(args.run),
        "frameCount": len(frames),
        "acceptedFrameCount": accepted,
        "blockedFrameCount": sum(1 for f in frames if f["status"] == BLOCKED),
        "pendingFrameCount": sum(1 for f in frames if f["status"] == REPAIR_NEEDED),
        "budgets": limits,
        "errors": errors,
        "frames": frames,
    }
    if paused and paused > time.time():
        report["pausedUntil"] = paused
        report["pausedUntilIso"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(paused))

    write_json(args.run / "run-status.json", report)
    print(
        json.dumps(
            {k: report[k] for k in ("status", "frameCount", "acceptedFrameCount", "blockedFrameCount", "pendingFrameCount")},
            indent=2,
        )
    )
    return 0 if overall == ACCEPTED else 2


# --------------------------------------------------------------------------- run


def cmd_run(args: argparse.Namespace) -> int:
    """Drive the queue to completion.

    One printed line per attempt and no per-attempt tool call, so an
    orchestrating agent can start this in the background and read
    run-status.json when it finishes rather than carrying the whole batch
    through its own context.
    """
    limits = budgets(args.run)
    python = args.python or sys.executable
    here = Path(__file__).resolve().parent
    processed = 0

    while True:
        paused = pause_until(args.run)
        if paused and paused > time.time():
            print(f"paused-until {time.strftime('%H:%M:%S', time.localtime(paused))}", flush=True)
            break
        ready, _ = pending_frames(args.run, limits)
        if not ready:
            break
        if args.max_attempts and processed >= args.max_attempts:
            print(f"stopping after {processed} attempts as requested", flush=True)
            break

        item = ready[0]
        frame = item["outputFrame"]
        attempt = item["nextAttempt"]
        directory = job_dir(args.run, frame) / f"attempt-{attempt:03d}"
        directory.mkdir(parents=True, exist_ok=True)
        job = read_json(job_dir(args.run, frame) / "job.json")
        processed += 1

        if args.worker:
            worker = subprocess.run(
                [python, str(args.worker), str(args.run), str(frame), str(attempt)],
                capture_output=True,
                text=True,
            )
            if worker.returncode != 0 and not (directory / "record.json").is_file():
                write_json(
                    directory / "record.json",
                    {
                        "outputFrame": frame,
                        "attempt": attempt,
                        "status": REPAIR_NEEDED,
                        "errorClass": WORKER_DIED,
                        "errorText": (worker.stderr or worker.stdout)[-2000:],
                    },
                )
                print(f"frame {frame:>3} attempt {attempt}: worker died", flush=True)
                continue

        raw = directory / "raw.png"
        if not raw.is_file():
            record_path = directory / "record.json"
            if not record_path.is_file():
                write_json(
                    record_path,
                    {
                        "outputFrame": frame,
                        "attempt": attempt,
                        "status": REPAIR_NEEDED,
                        "errorClass": TOOL_ERROR,
                        "errorText": "no image produced",
                    },
                )
            record = read_json(record_path)
            print(
                f"frame {frame:>3} attempt {attempt}: {record.get('errorClass', TOOL_ERROR)}",
                flush=True,
            )
            continue

        command = [
            python,
            str(here / "register_to_authority.py"),
            str(raw),
            str(job["authority"]),
            str(directory / "locked.png"),
            "--record",
            str(directory / "check.json"),
        ]
        registration = subprocess.run(command, capture_output=True, text=True)
        if registration.returncode != 0:
            record_path = directory / "record.json"
            record = read_json(record_path) if record_path.is_file() else {}
            record.update(
                {
                    "outputFrame": frame,
                    "attempt": attempt,
                    "status": REPAIR_NEEDED,
                    "errorClass": QUALITY,
                    "errorText": "registration rejected the frame",
                }
            )
            write_json(record_path, record)
            check = read_json(directory / "check.json") if (directory / "check.json").is_file() else {}
            print(
                f"frame {frame:>3} attempt {attempt}: quality - {'; '.join(check.get('errors', []))}",
                flush=True,
            )
            continue

        check = subprocess.run(
            [
                python,
                str(here / "check_frame_attempt.py"),
                str(args.run),
                str(frame),
                str(attempt),
            ],
            capture_output=True,
            text=True,
        )
        if check.returncode != 0:
            record_path = directory / "record.json"
            record = read_json(record_path) if record_path.is_file() else {}
            detail = directory / "check-attempt.json"
            reasons = read_json(detail).get("errors", []) if detail.is_file() else []
            record.update(
                {
                    "outputFrame": frame,
                    "attempt": attempt,
                    "status": REPAIR_NEEDED,
                    "errorClass": QUALITY,
                    "errorText": "; ".join(reasons) or "attempt check failed",
                }
            )
            write_json(record_path, record)
            print(
                f"frame {frame:>3} attempt {attempt}: quality - {'; '.join(reasons)}",
                flush=True,
            )
            continue

        select = argparse.Namespace(run=args.run, frame=frame, attempt=attempt)
        cmd_select(select)
        print(f"frame {frame:>3} attempt {attempt}: accepted", flush=True)

    return cmd_status(argparse.Namespace(run=args.run))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create one job per mapped output frame")
    init.add_argument("run", type=Path)
    init.add_argument("manifest", type=Path)
    init.add_argument("--source-frames", type=Path)
    init.add_argument("--prompt", type=Path)
    init.add_argument("--short-prompt", type=Path)
    init.add_argument("--color-reference", type=Path)
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    nxt = sub.add_parser("next", help="frames still owed an accepted attempt")
    nxt.add_argument("run", type=Path)
    nxt.add_argument("--limit", type=int, default=0)
    nxt.set_defaults(func=cmd_next)

    select = sub.add_parser("select", help="promote one attempt into frames/")
    select.add_argument("run", type=Path)
    select.add_argument("frame", type=int)
    select.add_argument("attempt", type=int)
    select.set_defaults(func=cmd_select)

    status = sub.add_parser("status", help="derive run-status.json from the records")
    status.add_argument("run", type=Path)
    status.set_defaults(func=cmd_status)

    run = sub.add_parser("run", help="drive the queue to completion")
    run.add_argument("run", type=Path)
    run.add_argument("--worker", type=Path, help="script that produces attempt raw.png")
    run.add_argument("--python", help="interpreter for the numpy/Pillow scripts")
    run.add_argument("--max-attempts", type=int, default=0)
    run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
