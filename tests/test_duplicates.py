from pathlib import Path
import unittest

from photo_agent.duplicates import find_duplicate_groups


class DuplicateTests(unittest.TestCase):
    def test_exact_duplicates_are_grouped(self) -> None:
        fixture = Path(__file__).parents[1] / "Фотокнига" / "spread_01.jpg"
        self.assertTrue(fixture.is_file())

        groups, warnings = find_duplicate_groups([fixture, fixture])

        self.assertEqual(warnings, [])
        exact = [group for group in groups if group.kind == "exact"]
        self.assertEqual(len(exact), 1)
        self.assertEqual(exact[0].paths, (fixture, fixture))
