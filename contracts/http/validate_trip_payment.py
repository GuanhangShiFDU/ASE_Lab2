"""Check illustrative trip/payment contracts, not a running business system."""
from pathlib import Path
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import copy
import importlib.util
import json
import yaml
from jsonschema import Draft202012Validator, FormatChecker

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE / 'examples/trip-payment'
HTTP_SCHEMAS = {
    'arrival-request':'TripVersionRequest', 'arrival-response':'ArrivalResult',
    'start-request':'StartTripRequest', 'start-response':'StartedTripResult',
    'complete-request':'TripVersionRequest', 'complete-response':'CompletedTripResult',
    'trip-ready-response':'TripResult', 'bill-pending-response':'TripBillResult',
    'bill-ready-response':'TripBillResult', 'payment-request':'CreatePaymentAttemptRequest',
    'payment-created-response':'PaymentAttemptResult', 'payment-unknown-response':'PaymentAttemptResult',
    'payment-succeeded-response':'PaymentAttemptResult', 'payment-failed-final-response':'PaymentAttemptResult',
    'payment-unpaid-state':'BillPaymentState', 'payment-pending-state':'BillPaymentState',
    'payment-paid-state':'BillPaymentState', 'payment-free-state':'BillPaymentState',
    'payment-operation-response':'OperationResult', 'version-conflict-response':'Error',
    'unknown-operation-response':'Error',
}
EVENTS = {'arrival-event', 'started-event', 'completed-event', 'measurement-event',
          'bill-event', 'attempt-event', 'receipt-event'}


def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def chain_checks(x):
    """Cross-field consistency of these examples, not a service state machine."""
    a, start, end, ready = [x[n] for n in ('arrival-response','start-response','complete-response','trip-ready-response')]
    trip, m = ready['trip'], ready['trip']['measurement']
    bill = x['bill-ready-response']['bill']
    attempts = [x[n]['attempt'] for n in ('payment-created-response','payment-unknown-response','payment-succeeded-response')]
    receipt = attempts[-1]['receipt']
    states = [x[n] for n in ('payment-unpaid-state','payment-pending-state','payment-paid-state')]
    events = [x[n] for n in EVENTS]
    d = bill['fareDetails']
    total = max(Decimal(d['minimumMinor']), Decimal(d['baseMinor'])
                + Decimal(d['ratePerMeterMinor']) * m['actualDistanceMeters']
                + Decimal(d['ratePerSecondMinor']) * m['durationSeconds'])
    checks = {
        'one ride across trip stages': a['rideOrderId'] == trip['rideOrderId']
            and all(v['trip']['rideOrderId'] == trip['rideOrderId'] for v in (start,end)),
        'one Trip': all(v['trip']['tripId'] == trip['tripId'] for v in (start,end)),
        'one assigned driver': all(v['trip']['driverId'] == a['driverId'] for v in (start,end,ready)),
        'versioned transitions': a['stateVersion'] == x['arrival-request']['expectedStateVersion'] + 1
            and start['stateVersion'] == x['start-request']['expectedStateVersion'] + 1 == a['stateVersion'] + 1
            and end['stateVersion'] == x['complete-request']['expectedStateVersion'] + 1 == start['stateVersion'] + 1,
        'measurement does not advance order state': end['stateVersion'] == ready['stateVersion'],
        'server trip time': stamp(a['arrivedAt']) <= stamp(trip['boardingConfirmedAt']) <= stamp(trip['startedAt']) < stamp(trip['endedAt'])
            and int((stamp(trip['endedAt'])-stamp(trip['startedAt'])).total_seconds()) == m['durationSeconds'],
        'missing then first verified measurement': start['trip']['measurement'] is None and end['trip']['measurement'] is None
            and m['measurementVersion'] == 1 and d['measurement'] == m,
        'bill source is Trip': bill['sourceId'] == trip['tripId'] and bill['rideOrderId'] == trip['rideOrderId']
            and x['bill-ready-response']['tripId'] == x['bill-pending-response']['tripId'] == trip['tripId'],
        'original fare and passenger': bill['ruleVersionId'] == trip['fareRuleVersionId']
            and bill['passengerId'] == trip['passengerId'],
        'exact decimal fare': int(total.quantize(Decimal('1'), rounding=ROUND_HALF_UP)) == bill['amountMinor'] == 2500,
        'pending fee is not a zero Bill': x['bill-pending-response']['status'] == 'FEE_PENDING' and x['bill-pending-response']['bill'] is None,
        'one immutable attempt': len({v['paymentAttemptId'] for v in attempts}) == 1
            and all(all(v[k] == attempts[0][k] for k in ('billId','billVersion','rideOrderId','passengerId','amountMinor','currency','requestedAt')) for v in attempts),
        'attempt uses authoritative bill': all(attempts[0][k] == bill[k] for k in ('billId','billVersion','rideOrderId','passengerId','amountMinor','currency')),
        'request is for same bill': all(x['payment-request'][k] == bill[k] for k in ('billId','billVersion')),
        'unknown is not final failure': [v['status'] for v in attempts] == ['CREATED','UNKNOWN','SUCCEEDED']
            and [v['statusVersion'] for v in attempts] == [1,2,3],
        'receipt matches successful attempt': all(receipt[k] == attempts[-1][k] for k in ('paymentAttemptId','billId','amountMinor','currency')),
        'payment time sequence': stamp(attempts[0]['requestedAt']) <= stamp(receipt['paidAt']) <= stamp(attempts[-1]['lastCheckedAt']),
        'creation operation is not paid': x['payment-operation-response']['operationType'] == 'createPaymentAttempt'
            and x['payment-operation-response']['status'] == 'SUCCEEDED'
            and x['payment-operation-response']['result'] == x['payment-created-response'],
        'payment read model': all(all(v[k] == bill[k] for k in ('billId','billVersion','amountMinor','currency')) for v in states)
            and states[1]['currentAttempt'] == attempts[1] and states[2]['receipt'] == receipt,
        'free is separate example': x['payment-free-state']['amountMinor'] == 0
            and x['payment-free-state']['billId'] != bill['billId'],
        'failed branch is a different attempt': x['payment-failed-final-response']['attempt']['paymentAttemptId'] != attempts[0]['paymentAttemptId']
            and x['payment-failed-final-response']['attempt']['status'] == 'FAILED_FINAL',
        'event trace': len({v['eventId'] for v in events}) == len(events)
            and len({v['correlationId'] for v in events}) == 1 and len({v['cityId'] for v in events}) == 1,
        'event arrival': all(x['arrival-event']['data'][k] == a[k] for k in ('rideOrderId','driverId','state','stateVersion','arrivedAt')),
        'event start': all(x['started-event']['data'][k] == start['trip'][k] for k in ('rideOrderId','tripId','driverId','passengerId','boardingConfirmedAt','startedAt'))
            and x['started-event']['data']['stateVersion'] == start['stateVersion'],
        'event completion': all(x['completed-event']['data'][k] == end['trip'][k] for k in ('rideOrderId','tripId','driverId','passengerId','startedAt','endedAt','measurement','fareRuleVersionId'))
            and x['completed-event']['data']['stateVersion'] == end['stateVersion'],
        'event measurement': x['measurement-event']['data']['measurement'] == m
            and x['measurement-event']['data']['tripId'] == trip['tripId']
            and x['measurement-event']['data']['stateVersion'] == ready['stateVersion'],
        'event Bill': all(bill[k] == v for k,v in x['bill-event']['data'].items()),
        'event pending attempt': all(attempts[1][k] == v for k,v in x['attempt-event']['data'].items() if k != 'updatedAt')
            and x['attempt-event']['data']['updatedAt'] == attempts[1]['lastCheckedAt'],
        'event Receipt': all(receipt[k] == v for k,v in x['receipt-event']['data'].items() if k not in ('rideOrderId','passengerId'))
            and x['receipt-event']['data']['rideOrderId'] == trip['rideOrderId']
            and x['receipt-event']['data']['passengerId'] == trip['passengerId'],
    }
    return checks


def main():
    spec=yaml.safe_load((HERE/'openapi.yaml').read_text(encoding='utf-8'))
    data={p.stem:json.loads(p.read_text(encoding='utf-8')) for p in EXAMPLES.glob('*.json')}
    assert set(data)==set(HTTP_SCHEMAS)|EVENTS
    def validator(name):
        return Draft202012Validator({'$ref':'#/components/schemas/'+name,'components':spec['components']}, format_checker=FormatChecker())
    for name,schema in HTTP_SCHEMAS.items(): validator(schema).validate(data[name])
    ev=Draft202012Validator(json.loads((HERE.parent/'events/event.schema.json').read_text()),format_checker=FormatChecker())
    module=importlib.util.spec_from_file_location('event_checks',HERE.parent/'events/validate.py')
    event_checks=importlib.util.module_from_spec(module);module.loader.exec_module(event_checks)
    for name in EVENTS:
        ev.validate(data[name]);assert not list(event_checks.semantic_errors(data[name])),name
    checks=chain_checks(data);assert all(checks.values()),[k for k,v in checks.items() if not v]
    negatives=0
    def reject(schema,value):
        nonlocal negatives
        assert list(validator(schema).iter_errors(value)),(schema,value)
        negatives+=1
    reject('StartTripRequest',{'expectedStateVersion':3,'boardingConfirmed':False})
    reject('StartTripRequest',{'expectedStateVersion':3})
    reject('TripVersionRequest',{'expectedStateVersion':0})
    reject('TripVersionRequest',{'expectedStateVersion':4,'amountMinor':0})
    for field,value in [('actualDistanceMeters',-1),('durationSeconds',1.5),('measurementVersion',0),('meteringSource','')]:
        v=copy.deepcopy(data['trip-ready-response']['trip']['measurement']);v[field]=value;reject('TripMeasurement',v)
    v=copy.deepcopy(data['start-response']);v['trip']['endedAt']='2026-10-28T02:15:30Z';reject('StartedTripResult',v)
    reject('StartedTripResult',data['complete-response'])
    reject('CompletedTripResult',data['start-response'])
    for field,value in [('amountMinor',0),('passengerId','someone-else')]:
        v=copy.deepcopy(data['payment-request']);v[field]=value;reject('CreatePaymentAttemptRequest',v)
    v=copy.deepcopy(data['payment-created-response']);v['attempt']['amountMinor']=0;reject('PaymentAttemptResult',v)
    v=copy.deepcopy(data['payment-succeeded-response']);v['attempt']['receipt']=None;reject('PaymentAttemptResult',v)
    v=copy.deepcopy(data['payment-unknown-response']);v['attempt']['receipt']=data['payment-paid-state']['receipt'];reject('PaymentAttemptResult',v)
    v=copy.deepcopy(data['payment-paid-state']);v['receipt']=None;reject('BillPaymentState',v)
    v=copy.deepcopy(data['payment-pending-state']);v['currentAttempt']=data['payment-failed-final-response']['attempt'];reject('BillPaymentState',v)
    v=copy.deepcopy(data['payment-free-state']);v['amountMinor']=1;reject('BillPaymentState',v)
    v=copy.deepcopy(data['bill-pending-response']);v['bill']=data['bill-ready-response']['bill'];reject('TripBillResult',v)
    # Mutations demonstrate cross-field checks catch misleading examples, not runtime behavior.
    mutations=[('trip-ready-response',['trip','measurement','durationSeconds'],721),
               ('bill-ready-response',['bill','sourceId'],'wrong-trip'),
               ('bill-ready-response',['bill','amountMinor'],2501),
               ('payment-succeeded-response',['attempt','receipt','amountMinor'],2501),
               ('payment-unknown-response',['attempt','paymentAttemptId'],'new-attempt'),
               ('payment-operation-response',['result','attempt','status'],'SUCCEEDED'),
               ('measurement-event',['data','measurement','actualDistanceMeters'],8001),
               ('receipt-event',['data','billId'],'wrong-bill')]
    for name,path,value in mutations:
        x=copy.deepcopy(data);target=x[name]
        for k in path[:-1]: target=target[k]
        target[path[-1]]=value
        assert not all(chain_checks(x).values()),(name,path)
        negatives+=1
    print(f'PASS {len(HTTP_SCHEMAS)} HTTP + {len(EVENTS)} event examples; {len(checks)} chain checks; {negatives} invalid examples rejected.')
    print('Static design checks only. No business service, payment channel or concurrent workflow was executed.')


if __name__=='__main__': main()
