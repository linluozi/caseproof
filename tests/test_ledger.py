import json
import os
import random
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from caseproof import CaseCountError, CaseLedger, certify_cases, default_key


class LedgerTests(unittest.TestCase):
    def test_same_case_twice_is_one_unique(self):
        ledger = CaseLedger()
        ledger.add({"a": 1})
        ledger.add({"a": 1})
        self.assertEqual((ledger.total, ledger.unique), (2, 1))
        self.assertEqual(ledger.duplicate_events, 1)
        self.assertEqual(ledger.duplicates()[0].count, 2)

    def test_dict_key_order_does_not_create_new_sample(self):
        ledger = CaseLedger()
        ledger.add({"a": 1, "b": 2})
        ledger.add({"b": 2, "a": 1})
        self.assertEqual(ledger.unique, 1)

    def test_type_tags_keep_json_values_apart(self):
        values = [1, 1.0, True, "1", b"1", None]
        ledger = CaseLedger().extend(values)
        self.assertEqual(ledger.unique, len(values))

    def test_negative_zero_and_nan_are_distinct_keys(self):
        ledger = CaseLedger().extend([0.0, -0.0, float("nan"), float("nan")])
        self.assertEqual(ledger.unique, 3)

    def test_bytes_and_non_ascii_strings(self):
        ledger = CaseLedger().extend([b"\x00\xff", "\u4f60\u597d", "\u00e9"])
        self.assertEqual(ledger.unique, 3)

    def test_labels_track_total_and_unique(self):
        ledger = CaseLedger()
        for label, case in [("empty", ""), ("empty", ""), ("wide", "x" * 10), ("wide", "y")]:
            ledger.add(case, label=label)
        counts = ledger.label_counts()
        self.assertEqual(counts["empty"], {"total": 2, "unique": 1})
        self.assertEqual(counts["wide"], {"total": 2, "unique": 2})

    def test_seed_reset_inside_generator_is_exposed(self):
        def one_doc():
            rng = random.Random(4321)  # BUG: the same document every call
            return {"words": [rng.random() for _ in range(40)]}

        ledger = CaseLedger().extend(one_doc() for _ in range(2000))
        self.assertEqual(ledger.unique, 1)
        report = ledger.certify(min_unique=1000)
        self.assertFalse(report["certified"])
        self.assertIn("2000", report["failures"][0])
        self.assertIn("1", report["failures"][0])

    def test_seed_outside_generator_gives_independent_cases(self):
        rng = random.Random(4321)

        def one_doc():
            return {"words": [rng.random() for _ in range(40)]}

        ledger = CaseLedger().extend(one_doc() for _ in range(2000))
        self.assertEqual(ledger.unique, 2000)

    def test_per_label_floor_reports_missing_label(self):
        ledger = CaseLedger().extend(["a", "b"], label="ascii")
        report = ledger.certify(min_unique=2, per_label={"ascii": 2, "empty": 1})
        self.assertFalse(report["certified"])
        self.assertTrue(any("empty" in item for item in report["failures"]))
        self.assertFalse(any("ascii" in item for item in report["failures"]))

    def test_require_raises_with_actionable_message(self):
        ledger = CaseLedger().extend(["x"] * 50)
        with self.assertRaises(CaseCountError) as ctx:
            ledger.require(min_unique=10)
        message = str(ctx.exception)
        self.assertIn("unique 1 < required 10", message)
        self.assertIn("repeated 50x", message)

    def test_custom_key_function(self):
        ledger = CaseLedger(key=lambda value: value["id"].encode())
        ledger.add({"id": "a", "payload": 1})
        ledger.add({"id": "a", "payload": 2})
        self.assertEqual(ledger.unique, 1)

    def test_key_must_return_bytes(self):
        ledger = CaseLedger(key=lambda value: str(value))
        with self.assertRaises(TypeError):
            ledger.add("x")

    def test_unserialisable_case_needs_custom_key(self):
        with self.assertRaises(TypeError):
            default_key(lambda: None)

    def test_report_is_json_serialisable(self):
        ledger = CaseLedger().extend([{"a": 1}, {"a": 1}, "x"], labels=["l", "l", None])
        text = json.dumps(ledger.report())
        self.assertIn("top_duplicates", text)
        self.assertEqual(ledger.report()["total"], 3)

    def test_empty_ledger_certifies_only_zero_floor(self):
        ledger = CaseLedger()
        self.assertEqual(ledger.unique_ratio, 0.0)
        self.assertTrue(ledger.certify(0)["certified"])
        self.assertFalse(ledger.certify(1)["certified"])

    def test_extend_rejects_mismatched_labels(self):
        with self.assertRaises(ValueError):
            CaseLedger().extend(["a", "b"], labels=["only-one"])

    def test_certify_cases_convenience(self):
        report = certify_cases(["a", "b", "a"], min_unique=2)
        self.assertTrue(report["certified"])
        self.assertEqual(report["unique"], 2)


class CliTests(unittest.TestCase):
    def _run(self, lines, *args):
        handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        try:
            for line in lines:
                handle.write(json.dumps(line) + "\n")
            handle.close()
            return subprocess.run(
                [sys.executable, "-m", "caseproof", handle.name, *args],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                capture_output=True,
                text=True,
            )
        finally:
            os.unlink(handle.name)

    def test_cli_rejects_short_unique_count(self):
        result = self._run([{"a": 1}, {"a": 1}, {"b": 2}], "--min-unique", "3")
        self.assertEqual(result.returncode, 1)
        self.assertIn("unique cases   : 2", result.stdout)
        self.assertIn("REJECTED", result.stdout)

    def test_cli_certifies_when_floor_is_met(self):
        result = self._run([{"a": 1}, {"a": 1}, {"b": 2}], "--min-unique", "2", "--quiet")
        self.assertEqual(result.returncode, 0)

    def test_cli_wrapped_labels_and_json_out(self):
        out = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        out.close()
        try:
            result = self._run(
                [{"case": "a", "label": "ascii"}, {"case": "b", "label": "ascii"}],
                "--wrapped",
                "--require-label",
                "empty=1",
                "--json-out",
                out.name,
            )
            self.assertEqual(result.returncode, 1)
            with open(out.name, encoding="utf-8") as handle:
                report = json.load(handle)
            self.assertEqual(report["labels"]["ascii"]["unique"], 2)
            self.assertFalse(report["certified"])
        finally:
            os.unlink(out.name)

    def test_cli_rejects_invalid_json(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        handle.write("{not json}\n")
        handle.close()
        try:
            result = subprocess.run(
                [sys.executable, "-m", "caseproof", handle.name],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                capture_output=True,
                text=True,
            )
        finally:
            os.unlink(handle.name)
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid JSON", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
