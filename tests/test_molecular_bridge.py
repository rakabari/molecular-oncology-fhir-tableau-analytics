"""Repository-layout smoke tests; run with python3 -m unittest discover -s tests -v."""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sql = load("sql_dashboard", "src/molecular_bridge/analytics/build_dashboard_data.py")
adapter = load("adapter", "src/molecular_bridge/integration/export_reconciliation_cases.py")
reconcile = load("reconcile", "src/molecular_bridge/integration/reconcile_cases.py")
genomic = load("genomic", "src/molecular_bridge/fhir/build_genomic_fhir.py")
validator = load("validator", "src/molecular_bridge/fhir/validate_fhir.py")


class MolecularBridgeTests(unittest.TestCase):
    def test_sql_to_fhir_linkage(self):
        fixture = ROOT / "examples/input/vendor_reports/101_MD-001_1_report.json"
        ehr = [entry["resource"] for entry in json.loads((ROOT / "examples/input/ehr_bundle.json").read_text())["entry"]]
        with tempfile.TemporaryDirectory() as folder:
            with sqlite3.connect(Path(folder) / "test.sqlite") as connection:
                connection.executescript(sql.SCHEMA)
                self.assertEqual(sql.load_reports(connection, fixture.parent, "MD")["loaded"], 5)
                cases = adapter.export_cases(connection)
                self.assertEqual(len(cases["cases"]), 5)
                self.assertEqual([row["status"] for row in reconcile.reconcile(cases, ehr)], ["matched"] * 5)
                self.assertEqual(connection.execute("SELECT geneSymbol FROM patient_reportsQ WHERE Accession='MD-001'").fetchone()[0], "FLT3")

    def test_genomic_bundle_references(self):
        case = json.loads((ROOT / "examples/input/vendor_cases.json").read_text())["cases"][0]
        ehr = [entry["resource"] for entry in json.loads((ROOT / "examples/input/ehr_bundle.json").read_text())["entry"]]
        bundle = genomic.report_bundle(case)
        self.assertTrue(validator.check(bundle, ehr)["valid_basic_checks"])
        bundle["entry"][0]["resource"]["result"][0]["reference"] = "Observation/missing"
        self.assertFalse(validator.check(bundle, ehr)["valid_basic_checks"])


if __name__ == "__main__":
    unittest.main()
