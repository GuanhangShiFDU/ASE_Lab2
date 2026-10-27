"""Validate design syntax and examples only; does not send HTTP requests."""
from pathlib import Path
import copy
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate_spec

HERE = Path(__file__).resolve().parent


def main():
    spec = yaml.safe_load((HERE / 'openapi.yaml').read_text(encoding='utf-8'))
    validate_spec(spec)
    checked = 0

    def validator(schema):
        return Draft202012Validator(
            {**schema, 'components': spec['components']},
            format_checker=FormatChecker(),
        )

    def visit(value):
        nonlocal checked
        if isinstance(value, dict):
            if 'schema' in value and 'example' in value:
                validator(value['schema']).validate(value['example'])
                checked += 1
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(spec)
    operations = [op for item in spec['paths'].values()
                  for method, op in item.items()
                  if method in ('get', 'post', 'put', 'patch', 'delete')]
    names = [op['operationId'] for op in operations]
    assert len(names) == len(set(names)), 'duplicate operationId'

    def rejects(name, instance):
        errors = list(validator({'$ref': '#/components/schemas/' + name}).iter_errors(instance))
        assert errors, f'{name} unexpectedly accepted invalid input: {instance}'

    point = {'latitude': 31.23, 'longitude': 121.47, 'coordinateSystem': 'WGS84'}
    rejects('Point', {**point, 'latitude': 91})
    rejects('Point', {**point, 'coordinateSystem': 'GCJ02'})
    rejects('CreateRideOrderRequest', {'sourceOrderId': None})
    rejects('CreateRideOrderRequest', {'quoteId': 'q1', 'sourceOrderId': None, 'passengerId': 'other'})
    rejects('Version', 0)
    rejects('UtcTime', '2026-10-27T02:00:00+08:00')
    quote = copy.deepcopy(spec['paths']['/v1/quotes']['post']['responses']['201']['content']['application/json']['example'])
    quote['estimatedAmountMinor'] = -1
    rejects('Quote', quote)
    quote['estimatedAmountMinor'] = 1.5
    rejects('Quote', quote)
    rejects('OperationResult', {'operationId': 'op1', 'operationType': 'createRideOrder',
                                'serverTime': '2026-10-27T02:00:00Z', 'status': 'SUCCEEDED'})
    print(f'PASS OpenAPI 3.1; {len(names)} operationIds; {checked} examples; 9 invalid schema cases rejected.')
    print('Static design validation only: no server, business execution or load test was performed.')


if __name__ == '__main__':
    main()
