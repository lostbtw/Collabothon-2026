"""Tests for the Borsuk Labs demo scenario; FA3_XSD=<schema folder> also validates the FA(3) files."""
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # sim/scenario
COMMITTED = HERE / "out"
SCRIPTS = ["bank_2026.py", "story_2026.py", "fa3_2026.py", "november_2026.py", "release_2026.py"]
NOT_GENERATED = {"pizzeria-amalfi-bank-statement-2025-v6.csv"}  # organisers' file, git-ignored


def generate(out):
    for script in SCRIPTS:
        subprocess.run([sys.executable, str(HERE / script)], check=True, capture_output=True, text=True,
                       env={**os.environ, "SCENARIO_OUT": str(out)})


def files(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and p.name not in NOT_GENERATED)


class Scenario(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.out1, cls.out2 = cls.tmp / "a", cls.tmp / "b"
        generate(cls.out1)
        generate(cls.out2)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def load(self, name):
        return json.loads((self.out1 / name).read_text(encoding="utf-8"))

    def assert_same_tree(self, a, b):
        self.assertEqual(files(a), files(b))
        _, mismatch, errors = filecmp.cmpfiles(a, b, files(a), shallow=False)
        self.assertEqual(mismatch + errors, [])

    def test_same_seed_gives_byte_identical_output(self):
        self.assert_same_tree(self.out1, self.out2)

    def test_committed_output_is_current(self):
        self.assert_same_tree(self.out1, COMMITTED)

    def test_story_table(self):
        sys.path.insert(0, str(HERE))
        try:
            import story_2026
            story_2026.check(story_2026.story_items(), self.load("people.json"))  # SystemExit on failure
        finally:
            sys.path.remove(str(HERE))

    def test_people(self):
        people = self.load("people.json")
        self.assertIn(("Jan Kowalski (SAMPLE)", "employee"), {(p["name"], p["role"]) for p in people})
        for p in people:
            self.assertTrue(p["email"].endswith(".sample"), p)
            self.assertIn("(SAMPLE)", p["name"])

    def test_sample_names_and_nips(self):
        for e in self.load("fa3_index.json"):
            self.assertIn("(SAMPLE)", e["counterparty"])
            if e["counterparty_tax_id"].isdigit():
                self.assertTrue(e["counterparty_tax_id"].startswith("999"), e["id"])
        for d in self.load("november_documents.json"):
            for side in (d["seller"], d["buyer"]):
                if side:
                    self.assertIn("(SAMPLE)", side["name"], d["id"])
                    if side["tax_id"] and side["tax_id"].isdigit():
                        self.assertTrue(side["tax_id"].startswith("999"), d["id"])
        for xml in (self.out1 / "fa3").rglob("*.xml"):
            for nip in re.findall(r"<NIP>(\d+)</NIP>", xml.read_text(encoding="utf-8")):
                self.assertTrue(nip.startswith("999"), xml.name)
        for csv in self.out1.glob("bank_*.csv"):
            for line in csv.read_text(encoding="utf-8").splitlines()[1:]:
                iban = line.split(";")[0].strip('"')
                self.assertTrue(iban.startswith("PL009999"), line)

    def test_release_plan(self):
        plan = self.load("release_plan.json")
        items = plan["items"]
        early = [i for i in items if i["via_model"] and i["scenario_date"] < "2026-11-01"]
        self.assertEqual(early, [], "nothing before November goes through extraction")
        self.assertEqual(sum(1 for i in items if i["channel"] == "bank"), 1070)
        documents = len(self.load("fa3_index.json")) + len(self.load("november_documents.json"))
        self.assertEqual(sum(1 for i in items if i["channel"] != "bank"), documents)
        self.assertEqual([i["document_id"] for i in items if i["mode"] == "live"], ["doc_rcpt412"])
        self.assertEqual([i["seq"] for i in items], list(range(1, len(items) + 1)))

    def test_ground_truth_links(self):
        truth = self.load("ground_truth.json")
        plan_refs = {(i["account"], i["entry_reference"]) for i in self.load("release_plan.json")["items"]
                     if i["channel"] == "bank"}
        linked = [(d["bank_line"]["account"], d["bank_line"]["entry_reference"])
                  for d in truth["documents"] if d["bank_line"]]
        unlinked = [(b["account"], b["entry_reference"]) for b in truth["bank_lines_without_document"]]
        self.assertTrue(set(linked) <= plan_refs)
        self.assertEqual(set(linked) | set(unlinked), plan_refs)
        self.assertEqual(set(linked) & set(unlinked), set())
        ids = {d["document_id"] for d in truth["documents"]}
        for cluster in truth["duplicates"]:
            self.assertIn(cluster["original"], ids)
            self.assertTrue(set(cluster["copies"]) <= ids)
        reimbursements = [d for d in truth["documents"] if d["paid_by"] == "employee_private"]
        total = sum(float(d["gross"]["amount"]) for d in reimbursements)
        self.assertAlmostEqual(total, 5169.00, places=2)

    @unittest.skipUnless(os.environ.get("FA3_XSD") and shutil.which("xmllint"), "set FA3_XSD to validate FA(3)")
    def test_fa3_schema(self):
        xsd = Path(os.environ["FA3_XSD"]) / "schemat.xsd"
        xmls = sorted(str(p) for p in (self.out1 / "fa3").rglob("*.xml"))
        result = subprocess.run(["xmllint", "--noout", "--schema", str(xsd), *xmls], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
