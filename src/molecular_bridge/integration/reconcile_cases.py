"""Compare identifiers to FHIR patient and order identifiers."""
import argparse
import json
import sqlite3
from pathlib import Path


def identifiers(resource):
    return {(x.get('system'), x.get('value')) for x in resource.get('identifier', [])}


def reconcile(vendor, resources):
    patients = [r for r in resources if r.get('resourceType') == 'Patient']
    orders = [r for r in resources if r.get('resourceType') == 'ServiceRequest']
    rows = []
    for case in vendor['cases']:
        mrn = ('urn:example:mrn', case['mrn'])
        accession = ('urn:example:accession', case['accession'])
        matched = [p for p in patients if mrn in identifiers(p)]
        patient_id = matched[0]['id'] if len(matched) == 1 else None
        candidate_orders = [o for o in orders if accession in identifiers(o)]
        order = candidate_orders[0] if len(candidate_orders) == 1 else None
        if len(matched) > 1 or len(candidate_orders) > 1:
            status = 'ambiguous_identifier'
        elif not matched:
            status = 'missing_patient'
        elif not order:
            status = 'missing_order'
        elif order.get('subject', {}).get('reference') != 'Patient/' + patient_id:
            status = 'patient_mismatch'
        else:
            status = 'matched'
        rows.append({'accession': case['accession'], 'patient_id': patient_id,
                     'order_id': order['id'] if order else None, 'status': status})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor', default='examples/input/vendor_cases.json')
    parser.add_argument('--ehr', default='examples/output/ehr_context.json')
    parser.add_argument('--database', default='examples/output/demo.sqlite')
    parser.add_argument('--output', default='examples/output/reconciliation.json')
    args = parser.parse_args()
    ehr = json.loads(Path(args.ehr).read_text())
    if ehr['source'] != 'case_fixture':
        parser.error('Local identifier; use a separate, approved linkage design for live EHR data')
    rows = reconcile(json.loads(Path(args.vendor).read_text()), ehr['resources'])
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(rows, indent=2) + '\n')
    with sqlite3.connect(args.database) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS case_reconciliation (accession TEXT PRIMARY KEY, patient_id TEXT, order_id TEXT, status TEXT NOT NULL)')
        conn.executemany('INSERT INTO case_reconciliation VALUES (:accession, :patient_id, :order_id, :status) ON CONFLICT(accession) DO UPDATE SET patient_id=excluded.patient_id, order_id=excluded.order_id, status=excluded.status', rows)
    print(f'Saved {len(rows)} reconciliation rows to {args.database}')


if __name__ == '__main__':
    main()
