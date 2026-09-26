"""Fetch a patient and available EHR context from Epic FHIR or a local fixture."""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urljoin, urlparse
import urllib.request


def request_json(url, token, base):
    if not url.startswith(base.rstrip('/') + '/'):
        raise ValueError('Refusing a URL outside the configured FHIR base')
    req = urllib.request.Request(url, headers={'Accept': 'application/fhir+json', 'Authorization': 'Bearer ' + token})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def search(base, resource, patient_id, token):
    from urllib.parse import urlencode
    url = base.rstrip('/') + '/' + resource + '?' + urlencode({'patient': patient_id, '_count': 50})
    records, visited = [], set()
    while url:
        if url in visited:
            raise ValueError('Pagination loop')
        visited.add(url)
        bundle = request_json(url, token, base)
        if bundle.get('resourceType') != 'Bundle':
            raise ValueError('Expected a FHIR Bundle')
        records.extend(e['resource'] for e in bundle.get('entry', []) if 'resource' in e)
        link = next((x['url'] for x in bundle.get('link', []) if x.get('relation') == 'next'), None)
        url = urljoin(base.rstrip('/') + '/', link) if link else None
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', help='Local Bundle, for the reproducible public example')
    parser.add_argument('--patient-id', help='Epic sandbox Patient ID, when using the live API')
    parser.add_argument('--base', default='https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4')
    parser.add_argument('--output', default='examples/output/ehr_context.json')
    parser.add_argument('--token-file', default='.local/epic_token.json')
    args = parser.parse_args()
    if args.fixture:
        bundle = json.loads(Path(args.fixture).read_text())
        resources = [e['resource'] for e in bundle.get('entry', [])]
        if bundle.get('resourceType') != 'Bundle':
            parser.error('Fixture must be a FHIR Bundle')
        origin = 'case_fixture'
    else:
        token = os.getenv('EPIC_ACCESS_TOKEN')
        if not token and Path(args.token_file).exists():
            token = json.loads(Path(args.token_file).read_text()).get('access_token')
        if not token or not args.patient_id:
            parser.error('Live mode needs --patient-id and EPIC_ACCESS_TOKEN')
        patient = request_json(args.base.rstrip('/') + '/Patient/' + args.patient_id, token, args.base)
        resources = [patient]
        for kind in ('ServiceRequest', 'DiagnosticReport'):
            try:
                resources.extend(search(args.base, kind, args.patient_id, token))
            except Exception as error:
                print(f'{kind} search unavailable or not permitted: {error}')
        origin = 'epic_sandbox'
    result = {'source': origin, 'fhir_base': args.base if origin == 'epic_sandbox' else None,
              'resources': resources}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, indent=2) + '\n')
    print(f"Saved {len(resources)} resources to {args.output} ({origin})")


if __name__ == '__main__':
    main()
