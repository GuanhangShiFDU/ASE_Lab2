"""Validate local event examples; no network, broker or business service is run."""
from datetime import datetime
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator, FormatChecker


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def semantic_errors(event):
    """Checks that JSON Schema cannot express through cross-field comparisons."""
    data = event["data"]
    key = {
        "RideOrder": "rideOrderId", "Bill": "billId",
        "PaymentAttempt": "paymentAttemptId", "Receipt": "receiptId",
    }[event["aggregateType"]]
    if event["aggregateId"] != data[key]:
        yield "aggregateId does not match data business ID"
    name = event["eventType"]
    if name == "ride.order-created.v1":
        seconds = (timestamp(data["matchDeadline"]) - timestamp(data["createdAt"])).total_seconds()
        if seconds != 60:
            yield "match deadline must be 60 seconds after creation (BR-02)"
    if name == "ride.invitation-issued.v1":
        seconds = (timestamp(data["expiresAt"]) - timestamp(data["createdAt"])).total_seconds()
        if not 0 < seconds <= 15:
            yield "invitation lifetime must be positive and at most 15 seconds"
    if name == "ride.trip-started.v1":
        if timestamp(data["startedAt"]) < timestamp(data["boardingConfirmedAt"]):
            yield "trip cannot start before boarding confirmation"
    if name == "ride.trip-completed.v1":
        if timestamp(data["endedAt"]) < timestamp(data["startedAt"]):
            yield "trip cannot end before it starts"
    if name == "ride.order-cancelled.v1" and data["acceptedAt"] is not None:
        if timestamp(data["cancelledAt"]) < timestamp(data["acceptedAt"]):
            yield "assigned cancellation cannot precede acceptance"
    for key in ("createdAt", "closedAt", "acceptedAt", "arrivedAt", "boardingConfirmedAt",
                "startedAt", "endedAt", "cancelledAt", "failedAt", "verifiedAt", "updatedAt", "paidAt"):
        if data.get(key) and timestamp(data[key]) > timestamp(event["occurredAt"]):
            yield f"{key} cannot be after the fact's occurredAt"


def main():
    base = Path(__file__).resolve().parent
    schema = json.loads((base / "event.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    declared = {branch["properties"]["eventType"]["const"] for branch in schema["oneOf"]}
    found, ids, failures = set(), set(), []
    for path in sorted((base / "examples").glob("*.json")):
        event = json.loads(path.read_text(encoding="utf-8"))
        errors = list(validator.iter_errors(event))
        if errors:
            failures.extend(f"{path.name}: {error.message}" for error in errors)
            continue
        failures.extend(f"{path.name}: {message}" for message in semantic_errors(event))
        if path.stem != event["eventType"]:
            failures.append(f"{path.name}: filename and eventType differ")
        if event["eventId"] in ids:
            failures.append(f"{path.name}: duplicate sample eventId")
        ids.add(event["eventId"])
        found.add(event["eventType"])
    if found != declared:
        failures.append(f"example coverage mismatch: missing={declared-found}, extra={found-declared}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"PASS: {len(found)} event types, schemas, example coverage and local field relationships")
    print("Static contract checks only; no runtime, delivery, concurrency or performance result is claimed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
