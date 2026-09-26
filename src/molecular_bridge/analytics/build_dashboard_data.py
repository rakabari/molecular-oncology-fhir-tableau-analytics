#!/usr/bin/env python3
"""Parse signed out report JSON into a Tableau-ready SQLite view.

Public adaptation of the case details, signed out report, JSON parsing, and
patient report stages.
"""

import argparse
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path


def named_sections(data):
    return {item.get("name"): item for item in data.get("content", []) if isinstance(item, dict)}


def section_content(sections, name, default=None):
    section = sections.get(name, {})
    return section.get("content", default) if isinstance(section, dict) else default


def report_identity(path):
    parts = path.name.split("_")
    if len(parts) != 4 or parts[3] != "report.json" or not parts[2].isdigit():
        raise ValueError("Expected case_accession_reportid_report.json")
    return parts[0], parts[1], int(parts[2])


def variants_from_report(data):
    sections = named_sections(data)
    header = section_content(sections, "compactReportHeader", {}) or {}
    signout = section_content(sections, "compactSignout", {}) or {}
    if not isinstance(header, dict) or not isinstance(signout, dict):
        raise ValueError("Unexpected vendor report header or signout shape")
    mrns = header.get("mrn") or []
    mrn = mrns[0] if isinstance(mrns, list) and mrns else (mrns if isinstance(mrns, str) else None)
    metadata = {"MRN": mrn, "PatientName": header.get("patient_name"),
                "DateOfBirth": header.get("date_of_birth"), "Disease": header.get("disease"),
                "SignedoutBy": signout.get("name"), "SignedoutDate": signout.get("date")}
    findings = []
    for section_name in ("compactClinicalImplications", "compactVUS"):
        section = section_content(sections, section_name, {}) or {}
        results = section.get("knowledgeBaseResults", []) if isinstance(section, dict) else []
        for result in results:
            finding = result.get("genomicFinding") or {}
            for variant in finding.get("variants", []):
                display = variant.get("displayData") or {}
                details = variant.get("additionalDetails") or {}
                if not isinstance(display, dict):
                    continue
                depth = details.get("depth")
                vaf = details.get("vaf")
                findings.append({"geneSymbol": display.get("geneSymbol"),
                    "transcript": display.get("transcript"), "cSyntax": display.get("cSyntax"),
                    "pSyntax": display.get("pSyntax"), "structuralSyntax": display.get("structuralSyntax"),
                    "VAF": float(str(vaf).replace("%", "")) if vaf not in (None, "") else None,
                    "Depth": int(str(depth).replace(",", "")) if depth not in (None, "") else None,
                    "Level": (result.get("inferredClassification") or {}).get("level"),
                    "VariantCallID": variant.get("variantCallId"),
                    "Interpretation": str(result.get("interpretation") or "").replace("Interpretation:", "").strip()})
    return metadata, findings


def specimen_type_from_case(data):
    specimen = (data.get("specimens") or [{}])[0]
    value = specimen.get("type") or {}
    return value.get("label") if isinstance(value, dict) else value


SCHEMA = """
CREATE TABLE IF NOT EXISTS case_details (
    Accession TEXT PRIMARY KEY, SpecimenType TEXT
);
CREATE TABLE IF NOT EXISTS reports (
    CaseID TEXT NOT NULL, Accession TEXT NOT NULL, ReportID INTEGER NOT NULL,
    MRN TEXT, PatientName TEXT, DateOfBirth TEXT, Disease TEXT, SignedoutBy TEXT, SignedoutDate TEXT,
    PRIMARY KEY (CaseID, Accession, ReportID)
);
CREATE TABLE IF NOT EXISTS patient_reports (
    CaseID TEXT NOT NULL, Accession TEXT NOT NULL, ReportID INTEGER NOT NULL, FindingIndex INTEGER NOT NULL,
    geneSymbol TEXT, transcript TEXT, cSyntax TEXT, pSyntax TEXT, structuralSyntax TEXT,
    VAF REAL, Depth INTEGER, Level TEXT, VariantCallID TEXT, Interpretation TEXT,
    PRIMARY KEY (CaseID, Accession, ReportID, FindingIndex),
    FOREIGN KEY (CaseID, Accession, ReportID) REFERENCES reports(CaseID, Accession, ReportID)
);
DROP VIEW IF EXISTS patient_reportsQ;
CREATE VIEW patient_reportsQ AS
WITH current_reports AS (
    SELECT r.* FROM reports r WHERE ReportID = (
        SELECT MAX(newer.ReportID) FROM reports newer WHERE newer.CaseID = r.CaseID AND newer.Accession = r.Accession
    )
), variants AS (
    SELECT r.Accession, r.MRN, r.PatientName, c.SpecimenType, r.DateOfBirth,
           p.transcript, p.geneSymbol,
           COALESCE(p.cSyntax, '') || COALESCE(p.structuralSyntax, '') AS cSyntax,
           COALESCE(p.pSyntax, '') || COALESCE(p.structuralSyntax, '') AS pSyntax,
           CASE WHEN lower(COALESCE(p.cSyntax, '') || COALESCE(p.pSyntax, '') || COALESCE(p.structuralSyntax, ''))
                     GLOB '*ins*' OR lower(COALESCE(p.cSyntax, '') || COALESCE(p.pSyntax, '') || COALESCE(p.structuralSyntax, ''))
                     GLOB '*del*' OR lower(COALESCE(p.cSyntax, '') || COALESCE(p.pSyntax, '') || COALESCE(p.structuralSyntax, ''))
                     GLOB '*dup*' THEN 'INDEL' ELSE 'SNV' END AS Variant_Type,
           p.VAF, p.Depth, p.Level AS Classification, p.Interpretation,
           r.SignedoutBy, r.SignedoutDate, r.Disease, r.CaseID, r.ReportID, p.FindingIndex
    FROM current_reports r JOIN patient_reports p
      ON p.CaseID = r.CaseID AND p.Accession = r.Accession AND p.ReportID = r.ReportID
    LEFT JOIN case_details c ON c.Accession = r.Accession
    WHERE r.Accession NOT LIKE '%CV-PS%' AND r.Accession NOT LIKE '%M1%'
)
SELECT Accession, MRN, PatientName, SpecimenType, DateOfBirth, transcript, geneSymbol,
       cSyntax, pSyntax, Variant_Type, VAF, Depth, Classification, Interpretation,
       SignedoutBy, SignedoutDate, Disease,
       COUNT(*) OVER (PARTITION BY geneSymbol, cSyntax, pSyntax) AS Frequency,
       COUNT(*) OVER (PARTITION BY geneSymbol, cSyntax, pSyntax, Disease) AS Frequency_in_Disease,
       CaseID, ReportID, FindingIndex
FROM variants;
"""


def load_case_details(conn, directory):
    count = 0
    if not directory:
        return count
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            accession = (data.get("specimens") or [{}])[0].get("accessionNumber")
            if not accession:
                continue
            conn.execute("INSERT INTO case_details VALUES (?, ?) ON CONFLICT(Accession) DO UPDATE SET SpecimenType=excluded.SpecimenType",
                         (str(accession), specimen_type_from_case(data)))
            count += 1
        except (OSError, ValueError, TypeError, IndexError, AttributeError) as error:
            print(f"Case detail file skipped: {path.name}: {error}", file=sys.stderr)
    return count


def load_reports(conn, directory, accession_prefix="MD"):
    counts = {"loaded": 0, "existing": 0, "skipped": 0, "failed": 0}
    for path in sorted(directory.glob("*_report.json")):
        try:
            case_id, accession, report_id = report_identity(path)
            if accession_prefix and not accession.startswith(accession_prefix):
                counts["skipped"] += 1
                continue
            if conn.execute("SELECT 1 FROM reports WHERE CaseID=? AND Accession=? AND ReportID=?",
                            (case_id, accession, report_id)).fetchone():
                counts["existing"] += 1
                continue
            metadata, findings = variants_from_report(json.loads(path.read_text(encoding="utf-8")))
            with conn:
                conn.execute("INSERT INTO reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (case_id, accession, report_id, *(metadata[k] for k in
                               ("MRN", "PatientName", "DateOfBirth", "Disease", "SignedoutBy", "SignedoutDate"))))
                for index, item in enumerate(findings, 1):
                    conn.execute("INSERT INTO patient_reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                 (case_id, accession, report_id, index, *(item[k] for k in
                                  ("geneSymbol", "transcript", "cSyntax", "pSyntax", "structuralSyntax", "VAF", "Depth", "Level", "VariantCallID", "Interpretation"))))
            counts["loaded"] += 1
        except (OSError, KeyError, TypeError, ValueError, sqlite3.Error) as error:
            counts["failed"] += 1
            print(f"Report skipped: {path.name}: {error}", file=sys.stderr)
    return counts


def export_dashboard(conn, output):
    cursor = conn.execute("SELECT * FROM patient_reportsQ ORDER BY Accession, FindingIndex")
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([column[0] for column in cursor.description])
        writer.writerows(cursor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", default="data/vendor_reports")
    parser.add_argument("--case-details-dir", type=Path, help="Optional case detail JSON folder for SpecimenType")
    parser.add_argument("--database", type=Path, default=Path("data/dashboard.sqlite"))
    parser.add_argument("--export-csv", type=Path, default=Path("data/tableau_signedout_variants.csv"))
    parser.add_argument("--accession-prefix", default="MD")
    args = parser.parse_args()
    reports_dir = Path(args.reports_dir)
    if not reports_dir.is_dir():
        parser.error(f"Report directory does not exist: {reports_dir}")
    args.database.parent.mkdir(parents=True, exist_ok=True)
    args.export_csv.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(args.database) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        details = load_case_details(conn, args.case_details_dir)
        counts = load_reports(conn, reports_dir, args.accession_prefix)
        conn.commit()
        export_dashboard(conn, args.export_csv)
    print(json.dumps({"case_details_loaded": details, **counts, "dashboard_csv": str(args.export_csv)}))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
