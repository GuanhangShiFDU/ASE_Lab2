"""Hermetic static contract checks, including cross-file refs and diagram coverage.

Run from any cwd. No server, credentials, external network or business requests.
"""
from pathlib import Path
import copy
from functools import lru_cache
import json
import re
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate_spec

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
METHODS = {'get', 'post', 'patch', 'put', 'delete'}
DIAGRAMS = ['quote-request-match', 'booking-recovery', 'cancel-rebook',
            'cancellation-races', 'pickup-trip-payment', 'trip-payment-recovery']
PORTS = {'estimateRoute', 'deliverHint', 'submitCharge', 'queryCharge', 'handlePaymentCallback'}
LOCAL = {'expireInvitation', 'expireMatchingDeadline', 'applyVerifiedPaymentFact'}


@lru_cache(maxsize=None)
def read(path):
    return yaml.safe_load(path.read_text(encoding='utf-8'))


def resolved(value, file, stack=()):
    """Resolve only existing local references; forbidden remote refs fail closed."""
    if isinstance(value, dict):
        if '$ref' in value:
            link = value['$ref']
            assert '://' not in link, f'Network ref not allowed: {link}'
            name, _, fragment = link.partition('#')
            target_file = (file.parent / name).resolve() if name else file
            assert HERE.parent.resolve() in target_file.parents, f'Ref outside contracts: {link}'
            key = (str(target_file), fragment)
            assert key not in stack, f'Cyclic ref: {key}'
            target = read(target_file)
            for part in fragment.lstrip('/').split('/') if fragment else []:
                target = target[part.replace('~1', '/').replace('~0', '~')]
            replacement = resolved(target, target_file, stack + (key,))
            # OAS 3.1 permits schema siblings; preserve them.
            return {**replacement, **resolved({k: v for k, v in value.items() if k != '$ref'}, file, stack)}
        return {k: resolved(v, file, stack) for k, v in value.items()}
    if isinstance(value, list):
        return [resolved(v, file, stack) for v in value]
    return value


def examples(value):
    if isinstance(value, dict):
        if 'schema' in value:
            if 'example' in value:
                yield value['schema'], value['example']
            for example in value.get('examples', {}).values():
                if 'value' in example:
                    yield value['schema'], example['value']
        for child in value.values():
            yield from examples(child)
    elif isinstance(value, list):
        for child in value:
            yield from examples(child)


def operations(spec):
    return {op['operationId']: (path, method, op)
            for path, item in spec['paths'].items()
            for method, op in item.items() if method in METHODS}


def consistency(spec, codes, internal=False):
    issues = []
    ids = []
    for path, item in spec['paths'].items():
        for method, op in item.items():
            if method not in METHODS:
                continue
            name = op['operationId']
            ids.append(name)
            if not op.get('x-owner') or not op.get('x-callers'):
                issues.append(f'{name}: owner/callers missing')
            declared = {p['name'] for p in item.get('parameters', []) + op.get('parameters', []) if p['in'] == 'path'}
            if declared != set(re.findall(r'{(\w+)}', path)):
                issues.append(f'{name}: path parameters mismatch')
            actual_codes = set()
            for status, response in op['responses'].items():
                if not status.startswith(('4', '5')):
                    continue
                for ex in response['content']['application/json'].get('examples', {}).values():
                    data = ex['value']
                    code = data['code']
                    actual_codes.add(code)
                    if str(codes.get(code)) != status:
                        issues.append(f'{name}: wrong status for {code}')
                    if code == 'OPERATION_PENDING' and data['outcome'] != 'UNKNOWN':
                        issues.append(f'{name}: pending result must be unknown')
            if actual_codes != set(op['x-error-codes']):
                issues.append(f'{name}: error example coverage mismatch')
            if internal:
                if op.get('security', spec.get('security')) != [{'serviceAuth': []}]:
                    issues.append(f'{name}: wrong internal identity')
                if not op.get('x-required-scope') or not op.get('servers'):
                    issues.append(f'{name}: internal scope/server missing')
                if op.get('x-delegated-subject-required') and not any(p['name'] == 'Delegation-Token' and p['required'] for p in op.get('parameters', [])):
                    issues.append(f'{name}: required delegation missing')
    if len(ids) != len(set(ids)):
        issues.append('Duplicate operationIds')
    return issues


def main():
    raw = {n: read(HERE / n) for n in ['openapi.yaml', 'internal.yaml']}
    specs = {n: resolved(s, (HERE / n).resolve()) for n, s in raw.items()}
    codes = read(HERE / 'error-codes.yaml')['codes']
    count = 0
    for name, spec in specs.items():
        validate_spec(spec)
        for schema, value in examples(spec):
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
            count += 1
        errors = consistency(spec, codes, name == 'internal.yaml')
        assert not errors, errors
    public = operations(specs['openapi.yaml'])
    internal = operations(specs['internal.yaml'])
    assert not (public.keys() & internal.keys()), 'operationIds must be globally distinct'
    assert len(public) == 28 and len(internal) == 16
    # Read actual requests in all six diagrams, not a hand-maintained list.
    available = set(public) | set(internal) | PORTS | LOCAL
    events = json.loads((HERE.parent / 'events/event.schema.json').read_text())['$defs']
    used_methods, used_events = set(), set()
    for name in DIAGRAMS:
        text = (ROOT / 'docs/diagrams' / (name + '.mmd')).read_text()
        calls = set(re.findall(r'\w+->>\w+:\s*([a-z][A-Za-z0-9]+)\(', text))
        assert calls <= available, (name, calls - available)
        found = set(re.findall(r'\b(?:ride|pricing|payment)\.[a-z-]+\.v1\b', text))
        assert found <= events.keys(), (name, found - events.keys())
        used_methods |= calls
        used_events |= found
    assert len(used_events) == 13, used_events
    guide = (HERE / 'core-api.md').read_text()
    for name in available:
        assert name in guide, f'{name} missing in consolidated human catalog'
    # Operation recovery has a single owner and a type-specific success result.
    mapping = {
        'createRideOrder': 'RideOrder', 'acceptInvitation': 'DecisionResult',
        'rejectInvitation': 'DecisionResult', 'cancelRideOrder': 'CancellationResult',
        'reportArrival': 'ArrivalResult', 'confirmBoardingAndStartTrip': 'StartedTripResult',
        'completeTrip': 'CompletedTripResult', 'createPaymentAttempt': 'PaymentAttemptResult',
        'updateMyProfile': 'MyProfile', 'setDriverAvailability': 'DriverServiceState',
        'openLocationSession': 'LocationSession',
    }
    success = raw['openapi.yaml']['components']['schemas']['OperationResult']['oneOf'][0]
    assert set(success['properties']['operationType']['enum']) == set(mapping)
    typed = {b['if']['properties']['operationType']['const']: b['then']['properties']['result']['$ref'].split('/')[-1] for b in success['allOf']}
    assert typed == mapping
    # Internal fact and event shape agreement; same naming and units.
    fact = specs['internal.yaml']['components']['schemas']['CancellationFact']['properties']['data']
    event_schema_file = (HERE.parent / 'events/event.schema.json').resolve()
    event_schema = resolved(read(event_schema_file), event_schema_file)
    assert fact == event_schema['$defs']['ride.order-cancelled.v1']
    tf = raw['internal.yaml']['paths']['/internal/v1/trips/{tripId}/fact']['get']['responses']['200']['content']['application/json']['example']
    assert tf['tripResult']['trip']['fareRuleVersionId'] == tf['fareRuleSnapshot']['fareRuleVersionId']
    assert tf['sourceVersion'] == json.loads((HERE / 'examples/trip-payment/measurement-event.json').read_text())['aggregateVersion']
    # Negative schema cases test meaningful contract boundaries.
    schemas = specs['openapi.yaml']['components']['schemas']
    rejected = 0
    def reject(schema, value):
        nonlocal rejected
        assert list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value)), value
        rejected += 1
    reject(schemas['UpdateProfileRequest'], {'expectedProfileVersion': 1, 'displayName': 'demo', 'contactReference': 'owned', 'roles': ['OPERATOR']})
    reject(schemas['SetAvailabilityRequest'], {'expectedAvailabilityVersion': 1, 'onlineIntent': True, 'serviceCityId': 'shanghai', 'activeOrderId': None})
    reject(schemas['LocationReportRequest'], {'sessionEpoch': 1, 'sequence': 0, 'observedAt': '2026-10-28T02:00:00Z', 'point': {'latitude': 31, 'longitude': 121, 'coordinateSystem': 'WGS84'}})
    reject(schemas['LocationReportRequest'], {'sessionEpoch': 1, 'sequence': 1, 'observedAt': '2026-10-28T02:00:00Z', 'point': {'latitude': 31, 'longitude': 121, 'coordinateSystem': 'GCJ02'}})
    payment = json.loads((HERE / 'examples/trip-payment/payment-operation-response.json').read_text())
    payment['operationType'] = 'createRideOrder'
    reject(schemas['OperationResult'], payment)
    reject(specs['internal.yaml']['components']['schemas']['Proposal'], {'driverId': 'driver1', 'matchPlanId': 'plan1', 'expectedAggregateVersion': 0, 'proposalId': 'p1'})
    reject(specs['internal.yaml']['components']['schemas']['MeasurementEvidence'], {'evidenceRef': 'e1', 'amountMinor': 0})
    # Deliberate spec mutations show consistency checks detect mismatches.
    for mutate in ['wrong-error-status', 'missing-delegation', 'wrong-service-identity', 'missing-path-parameter']:
        spec = copy.deepcopy(specs['internal.yaml'])
        op = spec['paths']['/internal/v1/quotes/{quoteId}']['get']
        if mutate == 'wrong-error-status':
            op['responses']['404']['content']['application/json']['examples']['NOT_FOUND']['value']['code'] = 'OPERATION_PENDING'
        elif mutate == 'missing-delegation':
            op['parameters'] = [p for p in op['parameters'] if p['name'] != 'Delegation-Token']
        elif mutate == 'wrong-service-identity':
            op['security'] = [{'bearerAuth': []}]
        else:
            op['parameters'] = [p for p in op['parameters'] if p['in'] != 'path']
        assert consistency(spec, codes, True), mutate
        rejected += 1
    print(f'PASS {len(public)} public + {len(internal)} internal operations; {count} inline examples; {len(codes)} error-code mappings.')
    print(f'PASS 6 diagrams: {len(used_methods)} request method names, 13 event names; 11 recovery operation types; {rejected} negative checks.')
    print('Static syntax/examples/references only. Human review, authorization enforcement, transactions and channel integration are not executed.')


if __name__ == '__main__':
    main()
