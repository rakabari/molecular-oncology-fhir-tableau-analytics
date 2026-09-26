"""Basic FHIR Bundle/reference/code checks; not a full HL7 profile validator."""
import argparse
import json
from pathlib import Path


def check(bundle, context):
    errors = []
    if bundle.get('resourceType') != 'Bundle' or bundle.get('type') != 'collection':
        errors.append('Expected a collection Bundle')
    resources = [e.get('resource', {}) for e in bundle.get('entry', [])]
    available = {r.get('resourceType', '') + '/' + r.get('id', '') for r in resources + context}
    if len(available) != len(resources + context):
        errors.append('Duplicate resource type/id')
    for resource in resources:
        label = resource.get('resourceType', '?') + '/' + resource.get('id', '?')
        if not resource.get('id') or not resource.get('resourceType'):
            errors.append(label + ': missing resourceType or id')
        if resource.get('resourceType') in ('DiagnosticReport', 'Observation'):
            if not resource.get('status') or not resource.get('code', {}).get('coding') and not resource.get('code', {}).get('text'):
                errors.append(label + ': missing status or code')
            refs = [resource.get('subject', {}).get('reference')]
            refs += [x.get('reference') for key in ('basedOn', 'result') for x in resource.get(key, [])]
            for ref in refs:
                if not ref or ref not in available:
                    errors.append(label + ': unresolved reference ' + str(ref))
        if resource.get('resourceType') == 'Observation':
            coding = resource.get('code', {}).get('coding', [])
            if not any(c.get('system') == 'http://loinc.org' and c.get('code') == '69548-6' for c in coding):
                errors.append(label + ': expected genomic variant assessment code')
    return {'valid_basic_checks': not errors, 'resources_checked': len(resources), 'errors': errors,
            'scope': 'Local structural and reference checks only; HL7 profile conformance not assessed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', default='examples/output/genomic_bundle.json')
    parser.add_argument('--ehr', default='examples/output/ehr_context.json')
    parser.add_argument('--output', default='examples/output/validation.json')
    args = parser.parse_args()
    context = json.loads(Path(args.ehr).read_text())['resources']
    outcome = check(json.loads(Path(args.bundle).read_text()), context)
    Path(args.output).write_text(json.dumps(outcome, indent=2) + '\n')
    print(json.dumps(outcome, indent=2))
    if outcome['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
