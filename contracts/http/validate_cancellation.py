"""Check design examples and their links, never execute a business workflow."""
from pathlib import Path
from datetime import datetime
import copy
import importlib.util
import json
import yaml
from jsonschema import Draft202012Validator, FormatChecker

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE / 'examples' / 'cancellation'
HTTP_SCHEMAS = {
    'cancel-request': 'CancelRideOrderRequest',
    'cancelled-response': 'CancellationResult',
    'fee-pending-response': 'CancellationFeeResult',
    'fee-ready-response': 'CancellationFeeResult',
    'fee-free-response': 'CancellationFeeResult',
    'operation-succeeded-response': 'OperationResult',
    'version-conflict-response': 'Error',
    'rebook-request': 'CreateRideOrderRequest',
    'rebook-response': 'RideOrder',
}


def time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def chain_errors(examples):
    """Consistency of this illustrative chain, not a cancellation implementation."""
    req = examples['cancel-request']
    result = examples['cancelled-response']
    c, order = result['cancellation'], result['rideOrder']
    event, bill_event = examples['cancelled-event'], examples['fee-created-event']
    fact = event['data']
    fee, pending = examples['fee-ready-response'], examples['fee-pending-response']
    bill = fee['bill']
    operation = examples['operation-succeeded-response']
    new_req, new = examples['rebook-request'], examples['rebook-response']
    rule = c['cancellationRule']
    checks = {
        'one old order': c['rideOrderId'] == order['rideOrderId'] == fact['rideOrderId'] == event['aggregateId'],
        'state and version': c['state'] == order['state'] == fact['state'] == 'CANCELLED'
            and c['stateVersion'] == order['stateVersion'] == fact['stateVersion'] == req['expectedStateVersion'] + 1,
        'caller reason': req['reason'] == c['reason'] == fact['reason'],
        'original allocation': c['driverId'] == order['assignedDriverId'] == fact['driverId']
            and c['acceptedAt'] == order['acceptedAt'] == fact['acceptedAt'],
        'immutable cancellation': all(c[k] == fact[k] for k in
            ('cancellationId', 'actorRole', 'previousState', 'cancelledAt')),
        'same rule': rule['cancellationRuleVersionId'] == fact['cancellationRuleVersionId'] == bill['ruleVersionId']
            and {k: rule[k] for k in ('graceSeconds', 'feeMinor', 'currency')} == fact['ruleSnapshot'],
        'exact 120 second example': (time(c['cancelledAt']) - time(c['acceptedAt'])).total_seconds() == rule['graceSeconds'],
        'consented boundary fee': bill['amountMinor'] == rule['feeMinor'] == req['maxAcceptedFeeMinor'] == 500,
        'bill source belongs to old cancellation': bill['rideOrderId'] == c['rideOrderId']
            and bill['sourceId'] == c['cancellationId'] == fee['cancellationId'] == pending['cancellationId']
            and fee['rideOrderId'] == pending['rideOrderId'] == c['rideOrderId'],
        'pending is not free': pending['status'] == 'FEE_PENDING' and pending['bill'] is None,
        'bill event': all(bill_event['data'][k] == v for k, v in bill.items())
            and bill_event['data']['passengerId'] == fact['passengerId'],
        'trace chain': event['causationId'] == result['operationId']
            and bill_event['causationId'] == event['eventId']
            and event['correlationId'] == bill_event['correlationId']
            and event['cityId'] == bill_event['cityId'] == order['cityId'],
        'replay original response': operation['operationType'] == 'cancelRideOrder'
            and operation['operationId'] == result['operationId'] and operation['result'] == result,
        'new order identity': new['rideOrderId'] != order['rideOrderId']
            and new['quoteId'] != order['quoteId'] and new['quoteId'] == new_req['quoteId'],
        'source history': new_req['sourceOrderId'] == new['sourceOrderId'] == order['rideOrderId'],
        'new matching state': new['state'] == 'MATCHING' and new['stateVersion'] == 1
            and new['assignedDriverId'] is None and new['acceptedAt'] is None,
        'new time sequence': time(new['createdAt']) >= time(c['cancelledAt'])
            and (time(new['matchDeadline']) - time(new['createdAt'])).total_seconds() == 60,
    }
    return [name for name, valid in checks.items() if not valid]


def main():
    spec = yaml.safe_load((HERE / 'openapi.yaml').read_text(encoding='utf-8'))
    data = {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in EXAMPLES.glob('*.json')}
    assert set(data) == set(HTTP_SCHEMAS) | {'cancelled-event', 'fee-created-event'}

    def validator(schema):
        return Draft202012Validator({'$ref': '#/components/schemas/' + schema,
            'components': spec['components']}, format_checker=FormatChecker())

    for name, schema in HTTP_SCHEMAS.items():
        validator(schema).validate(data[name])
    event_schema = json.loads((HERE.parent / 'events/event.schema.json').read_text(encoding='utf-8'))
    event_validator = Draft202012Validator(event_schema, format_checker=FormatChecker())
    module_spec = importlib.util.spec_from_file_location('event_checks', HERE.parent / 'events/validate.py')
    event_checks = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(event_checks)
    for name in ('cancelled-event', 'fee-created-event'):
        event_validator.validate(data[name])
        assert not list(event_checks.semantic_errors(data[name])), name
    assert not chain_errors(data), chain_errors(data)

    negative = 0

    def reject_schema(schema, instance):
        nonlocal negative
        assert list(validator(schema).iter_errors(instance)), f'accepted invalid {schema}'
        negative += 1

    req = data['cancel-request']
    for field in ('expectedStateVersion', 'maxAcceptedFeeMinor', 'reason'):
        reject_schema('CancelRideOrderRequest', {k: v for k, v in req.items() if k != field})
    for change in ({'actorRole': 'DRIVER'}, {'expectedStateVersion': 0},
                   {'maxAcceptedFeeMinor': -1}, {'maxAcceptedFeeMinor': 501}, {'reason': 'IGNORE_RULES'}):
        reject_schema('CancelRideOrderRequest', {**req, **change})
    reject_schema('CancellationFeeResult', {**data['fee-ready-response'], 'bill': None})
    reject_schema('CancellationFeeResult', {**data['fee-pending-response'], 'bill': data['fee-ready-response']['bill']})
    reject_schema('CancellationBill', {**data['fee-ready-response']['bill'], 'amountMinor': -1})
    reject_schema('Cancellation', {**data['cancelled-response']['cancellation'], 'previousState': 'IN_TRIP'})
    reject_schema('OperationResult', {k: v for k, v in data['operation-succeeded-response'].items() if k != 'result'})

    # These altered fixtures remain structurally plausible but break cross-file links.
    for example, path, value in [
        ('fee-ready-response', ('bill', 'sourceId'), 'cancel-other'),
        ('fee-ready-response', ('bill', 'amountMinor'), 0),
        ('cancelled-event', ('data', 'stateVersion'), 9),
        ('cancelled-event', ('data', 'cancelledAt'), '2026-10-27T02:02:09Z'),
        ('fee-created-event', ('causationId',), 'event-other'),
        ('operation-succeeded-response', ('result', 'operationId'), 'op-other'),
        ('rebook-response', ('rideOrderId',), data['cancelled-response']['rideOrder']['rideOrderId']),
        ('rebook-response', ('sourceOrderId',), 'order-other'),
        ('rebook-response', ('quoteId',), data['cancelled-response']['rideOrder']['quoteId']),
    ]:
        broken = copy.deepcopy(data)
        target = broken[example]
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        assert chain_errors(broken), f'undetected inconsistency: {example}/{path}'
        negative += 1
    print(f'PASS cancellation design: {len(HTTP_SCHEMAS)} HTTP examples; 2 events; 17 chain checks; {negative} invalid fixtures rejected.')
    print('Static examples only; no live API, database, races, broker retries or payment was executed.')


if __name__ == '__main__':
    main()
