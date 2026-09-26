"""SMART standalone launch with PKCE for an Epic sandbox public client."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer


def discover(base):
    url = base.rstrip('/') + '/.well-known/smart-configuration'
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4')
    parser.add_argument('--client-id', default=os.getenv('EPIC_CLIENT_ID'))
    parser.add_argument('--redirect-uri', default='http://127.0.0.1:8765/callback')
    parser.add_argument('--scope', default='launch/patient openid fhirUser patient/Patient.read patient/DiagnosticReport.read patient/ServiceRequest.read')
    parser.add_argument('--token-file', default='.local/epic_token.json')
    args = parser.parse_args()
    if not args.client_id:
        parser.error('Provide --client-id or EPIC_CLIENT_ID')
    config = discover(args.base)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    state = secrets.token_urlsafe(24)
    redirect = urllib.parse.urlparse(args.redirect_uri)
    if redirect.hostname not in ('127.0.0.1', 'localhost') or redirect.scheme != 'http':
        parser.error('This demo requires a local HTTP loopback redirect URI')
    params = {'response_type': 'code', 'client_id': args.client_id, 'redirect_uri': args.redirect_uri,
              'scope': args.scope, 'state': state, 'aud': args.base, 'code_challenge': challenge,
              'code_challenge_method': 'S256'}
    url = config['authorization_endpoint'] + '?' + urllib.parse.urlencode(params)
    outcome = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if urllib.parse.urlparse(self.path).path != redirect.path or query.get('state', [None])[0] != state:
                outcome['error'] = 'Invalid callback path or state'
            elif 'error' in query:
                outcome['error'] = query['error'][0]
            else:
                outcome['code'] = query.get('code', [None])[0]
            self.send_response(200 if outcome.get('code') else 400)
            self.end_headers()
            self.wfile.write(b'Authorization received. Return to your terminal.' if outcome.get('code') else b'Authorization failed.')

        def log_message(self, *args):
            pass

    server = HTTPServer((redirect.hostname, redirect.port), Callback)
    server.timeout = 180
    print('Opening sandbox authorization page. If needed, paste this URL into your browser:\n' + url)
    webbrowser.open(url)
    server.handle_request()
    server.server_close()
    if not outcome.get('code'):
        raise SystemExit(outcome.get('error', 'No callback received within 180 seconds'))
    body = urllib.parse.urlencode({'grant_type': 'authorization_code', 'code': outcome['code'],
                                   'redirect_uri': args.redirect_uri, 'client_id': args.client_id,
                                   'code_verifier': verifier}).encode()
    request = urllib.request.Request(config['token_endpoint'], data=body,
                                     headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(request, timeout=20) as response:
        token = json.load(response)
    print('Authorized. Patient context:', token.get('patient', '(none)'))
    print('Expires in seconds:', token.get('expires_in', 'unknown'))
    path = Path(args.token_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(token, handle)
    os.chmod(path, 0o600)
    print('Saved token locally to', path, '(ignored by Git)')


if __name__ == '__main__':
    main()
