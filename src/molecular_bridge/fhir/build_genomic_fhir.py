"""Map variant cases to a small FHIR R4 report Bundle (subset)."""
import argparse
import json
from pathlib import Path

LOINC = 'http://loinc.org'
HGNC = 'http://www.genenames.org/geneId'


def report_bundle(case):
    accession = case['accession']
    patient_ref = 'Patient/' + case['patient_id']
    order_ref = 'ServiceRequest/' + case['order_id']
    observations = []
    for index, variant in enumerate(case['variants'], 1):
        observations.append({'resourceType': 'Observation', 'id': f'variant-{accession}-{index}',
            'status': 'final', 'code': {'coding': [{'system': LOINC, 'code': '69548-6', 'display': 'Genetic variant assessment'}]},
            'subject': {'reference': patient_ref},
            'component': [
                {'code': {'coding': [{'system': LOINC, 'code': '48018-6', 'display': 'Gene studied ID'}]},
                 'valueCodeableConcept': {'coding': [{'system': HGNC, 'code': variant['hgnc_id'], 'display': variant['gene']}]}},
                {'code': {'coding': [{'system': LOINC, 'code': '48004-6', 'display': 'DNA change (c.HGVS)'}]}, 'valueCodeableConcept': {'text': variant['hgvs_c']}},
                {'code': {'coding': [{'system': LOINC, 'code': '48005-3', 'display': 'Amino acid change (p.HGVS)'}]}, 'valueCodeableConcept': {'text': variant['hgvs_p']}}
            ]})
    report = {'resourceType': 'DiagnosticReport', 'id': 'report-' + accession, 'status': 'final',
              'identifier': [{'system': 'urn:example:accession', 'value': accession}],
              'code': {'text': 'Molecular oncology panel'}, 'subject': {'reference': patient_ref},
              'basedOn': [{'reference': order_ref}], 'effectiveDateTime': case['signed_out'],
              'result': [{'reference': 'Observation/' + v['id']} for v in observations]}
    entries = [{'resource': r} for r in [report, *observations]]
    return {'resourceType': 'Bundle', 'type': 'collection', 'entry': entries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor', default='examples/input/vendor_cases.json')
    parser.add_argument('--accession', default='MD-001')
    parser.add_argument('--output', default='examples/output/genomic_bundle.json')
    args = parser.parse_args()
    cases = json.loads(Path(args.vendor).read_text())['cases']
    case = next((c for c in cases if c['accession'] == args.accession), None)
    if not case or not case.get('patient_id') or not case.get('order_id'):
        parser.error('Choose a case with patient_id and order_id')
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report_bundle(case), indent=2) + '\n')
    print('Saved illustrative FHIR Bundle to', args.output)


if __name__ == '__main__':
    main()
