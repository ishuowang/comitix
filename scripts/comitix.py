#!/usr/bin/env python3
"""Validate, preview, plan, and paint the Comitix contribution loop."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATTERN_PATH = REPO_ROOT / "pattern.json"
DEFAULT_MARKER_ROOT = REPO_ROOT / ".contributions"
PREVIEW_GLYPHS = "·░▒▓█"


class PatternError(ValueError):
    """Raised when the pattern or generated state is invalid."""


@dataclass(frozen=True)
class Pixel:
    target_date: date
    cycle: int
    column: int
    row: int
    level: int
    target_commits: int


@dataclass(frozen=True)
class CommitPlan:
    target_date: date
    cycle: int
    column: int
    row: int
    level: int
    slot: int
    target_commits: int
    marker_path: Path

    def serializable(self, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
        payload = asdict(self)
        payload["target_date"] = self.target_date.isoformat()
        try:
            payload["marker_path"] = self.marker_path.relative_to(repo_root).as_posix()
        except ValueError:
            payload["marker_path"] = self.marker_path.as_posix()
        return payload


def load_pattern(path: Path = DEFAULT_PATTERN_PATH) -> dict[str, Any]:
    try:
        pattern = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PatternError(f"pattern file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PatternError(f"invalid JSON in {path}: {exc}") from exc

    validate_pattern(pattern)
    return pattern


def validate_pattern(pattern: dict[str, Any]) -> None:
    if pattern.get("schema_version") != 1:
        raise PatternError("schema_version must be 1")

    cycle_weeks = pattern.get("cycle_weeks")
    if cycle_weeks != 53:
        raise PatternError("cycle_weeks must be exactly 53")

    try:
        anchor = date.fromisoformat(pattern["anchor_date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PatternError("anchor_date must be an ISO date") from exc
    if anchor.weekday() != 6:
        raise PatternError("anchor_date must be a Sunday")

    try:
        ZoneInfo(pattern["timezone"])
    except (KeyError, TypeError, ZoneInfoNotFoundError) as exc:
        raise PatternError("timezone must be a valid IANA timezone") from exc

    rows = pattern.get("rows")
    if not isinstance(rows, list) or len(rows) != 7:
        raise PatternError("rows must contain exactly seven strings")
    allowed = set("01234")
    for index, row in enumerate(rows):
        if not isinstance(row, str) or len(row) != cycle_weeks:
            raise PatternError(f"row {index} must contain exactly {cycle_weeks} cells")
        invalid = set(row) - allowed
        if invalid:
            raise PatternError(f"row {index} contains invalid levels: {sorted(invalid)}")

    levels = pattern.get("levels_to_commits")
    if not isinstance(levels, dict) or set(levels) != allowed:
        raise PatternError("levels_to_commits must define levels 0 through 4")
    mapped_counts = [levels[str(level)] for level in range(5)]
    if (
        any(not isinstance(count, int) or count < 0 for count in mapped_counts)
        or mapped_counts[0] != 0
        or mapped_counts != sorted(mapped_counts)
    ):
        raise PatternError("commit counts must be non-negative, ordered, and map level 0 to 0")

    segments = pattern.get("segments")
    if not isinstance(segments, list) or not segments:
        raise PatternError("segments must be a non-empty list")
    cursor = 0
    for segment in segments:
        if not isinstance(segment, dict):
            raise PatternError("each segment must be an object")
        if segment.get("start_week") != cursor:
            raise PatternError(f"segment {segment.get('name', '?')} does not start at week {cursor}")
        width = segment.get("width")
        if not isinstance(width, int) or width <= 0:
            raise PatternError("segment widths must be positive integers")
        cursor += width
    if cursor != cycle_weeks:
        raise PatternError(f"segment widths total {cursor}, expected {cycle_weeks}")

    for role in ("author", "committer"):
        identity = pattern.get(role)
        if not isinstance(identity, dict) or not identity.get("name") or not identity.get("email"):
            raise PatternError(f"{role} must include a name and email")


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO date: {value}") from exc


def anchor_date(pattern: dict[str, Any]) -> date:
    return date.fromisoformat(pattern["anchor_date"])


def today_for_pattern(pattern: dict[str, Any]) -> date:
    return datetime.now(ZoneInfo(pattern["timezone"])).date()


def pixel_for(pattern: dict[str, Any], target_date: date) -> Pixel | None:
    anchor = anchor_date(pattern)
    elapsed_days = (target_date - anchor).days
    if elapsed_days < 0:
        return None

    cycle_days = pattern["cycle_weeks"] * 7
    cycle, cycle_day = divmod(elapsed_days, cycle_days)
    column, row = divmod(cycle_day, 7)
    level = int(pattern["rows"][row][column])
    target_commits = pattern["levels_to_commits"][str(level)]
    return Pixel(
        target_date=target_date,
        cycle=cycle,
        column=column,
        row=row,
        level=level,
        target_commits=target_commits,
    )


def iter_dates(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def marker_path(marker_root: Path, target_date: date, slot: int) -> Path:
    return (
        marker_root
        / f"{target_date.year:04d}"
        / f"{target_date.month:02d}"
        / f"{target_date.day:02d}"
        / f"{slot:02d}.json"
    )


def marker_payload(pattern: dict[str, Any], plan: CommitPlan) -> dict[str, Any]:
    return {
        "pattern": pattern["id"],
        "date": plan.target_date.isoformat(),
        "cycle": plan.cycle,
        "column": plan.column,
        "row": plan.row,
        "level": plan.level,
        "slot": plan.slot,
        "target_commits": plan.target_commits,
    }


def marker_text(pattern: dict[str, Any], plan: CommitPlan) -> str:
    return json.dumps(
        marker_payload(pattern, plan),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def pending_plans(
    pattern: dict[str, Any],
    through: date,
    marker_root: Path = DEFAULT_MARKER_ROOT,
) -> list[CommitPlan]:
    start = anchor_date(pattern)
    if through < start:
        return []

    pending: list[CommitPlan] = []
    for target_date in iter_dates(start, through):
        pixel = pixel_for(pattern, target_date)
        if pixel is None:
            continue
        for slot in range(1, pixel.target_commits + 1):
            path = marker_path(marker_root, target_date, slot)
            plan = CommitPlan(
                target_date=target_date,
                cycle=pixel.cycle,
                column=pixel.column,
                row=pixel.row,
                level=pixel.level,
                slot=slot,
                target_commits=pixel.target_commits,
                marker_path=path,
            )
            if path.exists():
                if path.read_text(encoding="utf-8") != marker_text(pattern, plan):
                    raise PatternError(f"existing marker does not match the pattern: {path}")
                continue
            pending.append(plan)
    return pending


def preview_lines(pattern: dict[str, Any]) -> list[str]:
    return [
        "".join(PREVIEW_GLYPHS[int(level)] for level in row)
        for row in pattern["rows"]
    ]


def run_git(repo_root: Path, *args: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def ensure_clean_repo(repo_root: Path) -> None:
    try:
        inside = run_git(repo_root, "rev-parse", "--is-inside-work-tree")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PatternError(f"not a Git worktree: {repo_root}") from exc
    if inside != "true":
        raise PatternError(f"not a Git worktree: {repo_root}")
    if run_git(repo_root, "status", "--porcelain"):
        raise PatternError("paint requires a clean Git worktree")


def commit_timestamp(target_date: date, slot: int) -> str:
    minute = min(slot, 59)
    return f"{target_date.isoformat()}T12:{minute:02d}:00+08:00"


def paint(
    pattern: dict[str, Any],
    through: date,
    repo_root: Path = REPO_ROOT,
    marker_root: Path = DEFAULT_MARKER_ROOT,
    *,
    dry_run: bool = False,
    quiet: bool = False,
) -> int:
    plans = pending_plans(pattern, through, marker_root)
    if dry_run:
        if not quiet:
            print(json.dumps([plan.serializable(repo_root) for plan in plans], indent=2))
        return len(plans)

    ensure_clean_repo(repo_root)
    for plan in plans:
        plan.marker_path.parent.mkdir(parents=True, exist_ok=True)
        plan.marker_path.write_text(marker_text(pattern, plan), encoding="utf-8")
        relative_path = plan.marker_path.relative_to(repo_root).as_posix()
        run_git(repo_root, "add", "--", relative_path)

        stamp = commit_timestamp(plan.target_date, plan.slot)
        env = os.environ.copy()
        env.update(
            {
                "GIT_AUTHOR_NAME": pattern["author"]["name"],
                "GIT_AUTHOR_EMAIL": pattern["author"]["email"],
                "GIT_AUTHOR_DATE": stamp,
                "GIT_COMMITTER_NAME": pattern["committer"]["name"],
                "GIT_COMMITTER_EMAIL": pattern["committer"]["email"],
                "GIT_COMMITTER_DATE": stamp,
            }
        )
        message = (
            f"music: paint {plan.target_date.isoformat()} "
            f"pixel {plan.slot}/{plan.target_commits}"
        )
        run_git(repo_root, "commit", "-m", message, "--", relative_path, env=env)
        if not quiet:
            print(f"painted {relative_path}")

    if not quiet:
        print(f"created {len(plans)} commit(s) through {through.isoformat()}")
    return len(plans)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pattern",
        type=Path,
        default=DEFAULT_PATTERN_PATH,
        help="path to pattern.json",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="validate the pattern")
    subparsers.add_parser("preview", help="render the 7×53 pattern in the terminal")
    subparsers.add_parser("today", help="print today's date in the pattern timezone")

    plan_parser = subparsers.add_parser("plan", help="list missing deterministic commits")
    plan_parser.add_argument("--through", required=True, type=parse_iso_date)

    paint_parser = subparsers.add_parser("paint", help="create all missing commits")
    paint_parser.add_argument("--through", required=True, type=parse_iso_date)
    paint_parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        pattern = load_pattern(args.pattern)
        if args.command == "validate":
            print(
                f"valid: {pattern['id']} "
                f"({len(pattern['rows'])}×{pattern['cycle_weeks']})"
            )
        elif args.command == "preview":
            print("\n".join(preview_lines(pattern)))
        elif args.command == "today":
            print(today_for_pattern(pattern).isoformat())
        elif args.command == "plan":
            plans = pending_plans(pattern, args.through)
            print(json.dumps([plan.serializable() for plan in plans], indent=2))
        elif args.command == "paint":
            paint(pattern, args.through, dry_run=args.dry_run)
        return 0
    except (PatternError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
