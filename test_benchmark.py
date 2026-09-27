"""Keep benchmark math and its start-synchronized workload reproducible."""

import unittest

import benchmark


class BenchmarkTests(unittest.TestCase):
    def test_checksum_is_deterministic(self):
        expected = sum(value ^ (value >> 3) for value in range(1000))
        self.assertEqual(benchmark.checksum_for_work(1000), expected)
        self.assertEqual(benchmark.checksum_for_work(1000), expected)

    def test_paired_overhead_uses_workload_runtime(self):
        trials = [
            {"baseline": {"runtime": 2.0}, "monitored": {"runtime": 2.1}},
            {"baseline": {"runtime": 4.0}, "monitored": {"runtime": 3.8}},
        ]
        values = benchmark.paired_overheads(trials)
        self.assertAlmostEqual(values[0], 5.0)
        self.assertAlmostEqual(values[1], -5.0)

    def test_benchmark_rejects_too_little_work_or_repetition(self):
        for kwargs in (
            {"repeats": 2, "units": 50_000_000, "intervals": (0.1,)},
            {"repeats": 3, "units": 1_000, "intervals": (0.1,)},
            {"repeats": 3, "units": 50_000_000, "intervals": (0.01,)},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                benchmark.run(**kwargs)

    def test_output_database_does_not_replace_a_previous_run(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "benchmark-20260927-000000.sqlite3"
            existing.write_text("keep this earlier result")
            first = benchmark.new_database_path(directory, "20260927-000000")
            first.write_text("first benchmark")
            second = benchmark.new_database_path(directory, "20260927-000000")
            self.assertNotEqual(first, existing)
            self.assertNotEqual(second, first)
            self.assertEqual(existing.read_text(), "keep this earlier result")


if __name__ == "__main__":
    unittest.main()
