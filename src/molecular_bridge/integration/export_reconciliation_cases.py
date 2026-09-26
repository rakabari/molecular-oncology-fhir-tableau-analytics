#!/usr/bin/env python3
"""Export current molecular cases from cgw_sql_dashboard.py for FHIR reconciliation.

The output matches the input expected by reconcile_cases.py in MolecularBridge.
It contains MRNs and accessions, so keep real-data output outside a public repo.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path


CURRENT_REPORTS = """
SELECT r.CaseID, r.Accession, r.ReportID, r.MRN, r.Disease, r.SignedoutDate,
       COUNT(p.FindingIndex) AS variant_count
FROM reports AS r
LEFT JOIN patient_reports AS p
  ON p.CaseID = r.CaseID AND p.Accession = r.Accession AND p.ReportID = r.ReportID
WHERE r.ReportID = (
    SELECT MAX(newer.ReportID) FROM reports AS newer
    WHERE newer.CaseID = r.CaseID AND newer.Accession = r.Accession
)
GROUP BY r.CaseID, r.Accession, r.ReportID, r.MRN, r.Disease, r.SignedoutDate
ORDER BY r.Accession, r.CaseID
"""


def export_cases(connection):
    connection.row_factory = sqlite3.Row
    rows = connection.execute(CURRENT_REPORTS).fetchall()
    cases = []
    for row in rows:
        if not row["Accession"] or not row["MRN"]:
            # Reconciliation cannot identify an EHR patient without both keys.
            continue
        cases.append({"case_id": row["CaseID"], "accession": row["Accession"],
                      "report_id": row["ReportID"], "mrn": row["MRN"],
                      "disease": row["Disease"], "signed_out": row["SignedoutDate"],
                      "variant_count": row["variant_count"]})
    return {"cases": cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/dashboard.sqlite"))
    parser.add_argument("--output", type=Path, default=Path("data/reconciliation_cases.json"))
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error(f"Database not found: {args.database}")
    try:
        with sqlite3.connect(f"file:{args.database.resolve()}?mode=ro", uri=True) as connection:
            result = export_cases(connection)
    except sqlite3.Error as error:
        parser.error(f"Could not read dashboard tables: {error}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {len(result['cases'])} current cases to {args.output}")
    print("This JSON contains patient identifiers; keep real-data output out of GitHub.", file=sys.stderr)


if __name__ == "__main__":
    main()
