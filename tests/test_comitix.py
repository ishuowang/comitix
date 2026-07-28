from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts.comitix import (
    PatternError,
    anchor_date,
    load_pattern,
    marker_text,
    paint,
    pending_plans,
    pixel_for,
    preview_lines,
    validate_pattern,
)


ROOT = Path(__file__).resolve().parents[1]


class PatternTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pattern = load_pattern(ROOT / "pattern.json")
        cls.anchor = anchor_date(cls.pattern)

    def test_pattern_is_exactly_seven_by_fifty_three(self) -> None:
        self.assertEqual(53, self.pattern["cycle_weeks"])
        self.assertEqual(7, len(self.pattern["rows"]))
        self.assertEqual({53}, {len(row) for row in self.pattern["rows"]})
        self.assertEqual(53, sum(segment["width"] for segment in self.pattern["segments"]))

    def test_cassette_replaces_equalizer_and_double_beat(self) -> None:
        names = {segment["name"] for segment in self.pattern["segments"]}
        self.assertIn("cassette", names)
        self.assertNotIn("equalizer", names)
        self.assertNotIn("double-beat", names)
        cassette = next(segment for segment in self.pattern["segments"] if segment["name"] == "cassette")
        self.assertEqual((17, 8), (cassette["start_week"], cassette["width"]))

    def test_anchor_and_week_boundaries(self) -> None:
        anchor_pixel = pixel_for(self.pattern, self.anchor)
        self.assertIsNotNone(anchor_pixel)
        self.assertEqual((0, 0, 0), (anchor_pixel.column, anchor_pixel.row, anchor_pixel.cycle))

        monday_pixel = pixel_for(self.pattern, self.anchor + timedelta(days=1))
        self.assertEqual((0, 1), (monday_pixel.column, monday_pixel.row))

        next_sunday = pixel_for(self.pattern, self.anchor + timedelta(days=7))
        self.assertEqual((1, 0), (next_sunday.column, next_sunday.row))

        last_pixel = pixel_for(self.pattern, self.anchor + timedelta(days=370))
        self.assertEqual((52, 6, 0), (last_pixel.column, last_pixel.row, last_pixel.cycle))

        repeated = pixel_for(self.pattern, self.anchor + timedelta(days=371))
        self.assertEqual((0, 0, 1), (repeated.column, repeated.row, repeated.cycle))
        self.assertEqual(anchor_pixel.level, repeated.level)

    def test_before_anchor_has_no_pixel_or_plan(self) -> None:
        before = self.anchor - timedelta(days=1)
        self.assertIsNone(pixel_for(self.pattern, before))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual([], pending_plans(self.pattern, before, Path(tmp)))

    def test_preview_is_seven_by_fifty_three(self) -> None:
        preview = preview_lines(self.pattern)
        self.assertEqual(7, len(preview))
        self.assertEqual({53}, {len(row) for row in preview})

    def test_invalid_dimensions_fail_fast(self) -> None:
        broken = json.loads(json.dumps(self.pattern))
        broken["rows"][0] = broken["rows"][0][:-1]
        with self.assertRaises(PatternError):
            validate_pattern(broken)

    def test_markers_make_planning_idempotent(self) -> None:
        target = self.anchor + timedelta(days=2)
        with tempfile.TemporaryDirectory() as tmp:
            marker_root = Path(tmp)
            plans = pending_plans(self.pattern, target, marker_root)
            self.assertGreater(len(plans), 0)
            for plan in plans:
                plan.marker_path.parent.mkdir(parents=True, exist_ok=True)
                plan.marker_path.write_text(marker_text(self.pattern, plan), encoding="utf-8")
            self.assertEqual([], pending_plans(self.pattern, target, marker_root))

    def test_corrupt_existing_marker_is_rejected(self) -> None:
        target = self.anchor + timedelta(days=2)
        with tempfile.TemporaryDirectory() as tmp:
            marker_root = Path(tmp)
            plan = pending_plans(self.pattern, target, marker_root)[0]
            plan.marker_path.parent.mkdir(parents=True, exist_ok=True)
            plan.marker_path.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(PatternError):
                pending_plans(self.pattern, target, marker_root)

    def test_paint_creates_authored_commits_once(self) -> None:
        target = self.anchor + timedelta(days=2)
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            marker_root = repo_root / ".contributions"
            subprocess.run(
                ["git", "init", "-b", "main"],
                cwd=repo_root,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            (repo_root / "seed.txt").write_text("seed\n", encoding="utf-8")
            subprocess.run(["git", "add", "seed.txt"], cwd=repo_root, check=True)
            seed_env = os.environ.copy()
            seed_env.update(
                {
                    "GIT_AUTHOR_NAME": "test",
                    "GIT_AUTHOR_EMAIL": "test@example.com",
                    "GIT_COMMITTER_NAME": "test",
                    "GIT_COMMITTER_EMAIL": "test@example.com",
                }
            )
            subprocess.run(
                ["git", "commit", "-m", "seed"],
                cwd=repo_root,
                env=seed_env,
                check=True,
                stdout=subprocess.DEVNULL,
            )

            expected = len(pending_plans(self.pattern, target, marker_root))
            self.assertGreater(expected, 0)
            self.assertEqual(
                expected,
                paint(
                    self.pattern,
                    target,
                    repo_root,
                    marker_root,
                    quiet=True,
                ),
            )
            self.assertEqual(
                0,
                paint(
                    self.pattern,
                    target,
                    repo_root,
                    marker_root,
                    quiet=True,
                ),
            )

            commit_count = subprocess.check_output(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=repo_root,
                text=True,
            ).strip()
            self.assertEqual(expected + 1, int(commit_count))
            author_email = subprocess.check_output(
                ["git", "show", "-s", "--format=%ae", "HEAD"],
                cwd=repo_root,
                text=True,
            ).strip()
            self.assertEqual(self.pattern["author"]["email"], author_email)


if __name__ == "__main__":
    unittest.main()
