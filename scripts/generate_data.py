"""
Synthetic data generator for the serverless data platform.

Generates realistic IoT sensor readings, API events, and transaction
records with configurable volume, categories, and error rates.
"""

import json
import math
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


# Realistic source IDs
SENSOR_SOURCES = [
    "sensor-temp-floor1-001", "sensor-temp-floor1-002", "sensor-temp-floor2-001",
    "sensor-humidity-lobby-001", "sensor-humidity-server-001", "sensor-humidity-warehouse-001",
    "sensor-pressure-hvac-001", "sensor-pressure-hvac-002",
    "sensor-air-quality-floor1-001", "sensor-air-quality-floor2-001",
    "sensor-network-switch-001", "sensor-network-router-001",
    "sensor-temp-exterior-001", "sensor-temp-datacenter-001", "sensor-temp-datacenter-002",
]

API_SOURCES = [
    "web-app-frontend", "mobile-app-ios", "mobile-app-android",
    "partner-api-acme", "partner-api-globex", "internal-batch-processor",
    "iot-gateway-north", "iot-gateway-south", "admin-dashboard",
]

TRANSACTION_SOURCES = [
    "payment-gateway-stripe", "payment-gateway-paypal", "pos-terminal-store-1",
    "pos-terminal-store-2", "online-checkout", "subscription-billing",
    "refund-processor", "marketplace-seller-001", "marketplace-seller-002",
]

LOCATIONS = [
    "us-east-1", "us-west-2", "eu-west-1", "eu-central-1",
    "ap-southeast-1", "ap-northeast-1", "Building-A-Floor-1",
    "Building-A-Floor-2", "Building-B-Floor-1", "Warehouse-North",
    "Datacenter-Primary", "Datacenter-DR",
]

TRANSACTION_CATEGORIES = [
    "electronics", "clothing", "food", "software", "services",
    "subscription", "refund", "hardware", "consulting", "advertising",
]

EVENT_TYPES_API = [
    "page_view", "click", "form_submit", "api_call", "error",
    "login", "logout", "search", "purchase", "notification_sent",
]

TAGS = [
    "production", "monitoring", "critical", "non-critical", "automated",
    "manual", "high-priority", "low-priority", "test", "real-time",
]


def generate_sensor_reading(
    timestamp: Optional[datetime] = None,
    source_id: Optional[str] = None,
) -> dict[str, Any]:
    """Generate a realistic sensor reading."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    if source_id is None:
        source_id = random.choice(SENSOR_SOURCES)

    # Determine sensor type from source_id
    if "temp" in source_id:
        unit = "celsius"
        # Simulate realistic temperature with daily cycle
        hour = timestamp.hour
        base_temp = 22.0  # Base indoor temperature
        if "exterior" in source_id:
            base_temp = 15.0 + 10 * math.sin((hour - 6) * math.pi / 12)
        elif "datacenter" in source_id:
            base_temp = 20.0 + random.uniform(-1, 3)
        value = round(base_temp + random.gauss(0, 1.5), 2)
    elif "humidity" in source_id:
        unit = "percent"
        base_humidity = 45.0
        if "warehouse" in source_id:
            base_humidity = 55.0
        elif "server" in source_id:
            base_humidity = 35.0
        value = round(max(10, min(95, base_humidity + random.gauss(0, 5))), 2)
    elif "pressure" in source_id:
        unit = "hpa"
        value = round(1013.25 + random.gauss(0, 10), 2)
    elif "air" in source_id:
        unit = "ppm"
        value = round(max(0, 30 + random.gauss(0, 15)), 2)
    elif "network" in source_id:
        unit = random.choice(["mbps", "ms"])
        if unit == "mbps":
            value = round(max(0, 950 + random.gauss(0, 50)), 2)
        else:
            value = round(max(0.1, 5 + random.gauss(0, 2)), 2)
    else:
        unit = "count"
        value = round(random.uniform(0, 100), 2)

    quality_score = round(random.uniform(0.85, 1.0), 4)
    # Occasionally generate low quality readings
    if random.random() < 0.02:
        quality_score = round(random.uniform(0.1, 0.4), 4)

    record = {
        "source_id": source_id,
        "record_type": "sensor_reading",
        "value": value,
        "unit": unit,
        "timestamp": timestamp.isoformat(),
        "location": random.choice(LOCATIONS),
        "quality_score": quality_score,
        "tags": random.sample(TAGS, k=random.randint(1, 3)),
        "metadata": {
            "firmware_version": f"v{random.randint(1, 3)}.{random.randint(0, 9)}.{random.randint(0, 99)}",
            "battery_level": random.randint(20, 100),
            "signal_strength": random.randint(-90, -30),
        },
    }

    return record


def generate_api_event(
    timestamp: Optional[datetime] = None,
    source_id: Optional[str] = None,
) -> dict[str, Any]:
    """Generate a realistic API event."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    if source_id is None:
        source_id = random.choice(API_SOURCES)

    event_type = random.choice(EVENT_TYPES_API)

    record = {
        "source_id": source_id,
        "record_type": "api_event",
        "event_type": event_type,
        "timestamp": timestamp.isoformat(),
        "payload": {
            "endpoint": f"/api/v1/{random.choice(['users', 'orders', 'products', 'analytics'])}",
            "method": random.choice(["GET", "POST", "PUT", "DELETE"]),
            "status_code": random.choice([200, 200, 200, 200, 201, 400, 404, 500]),
            "response_time_ms": round(random.gauss(150, 50), 2),
            "user_agent": random.choice([
                "Mozilla/5.0", "PostmanRuntime/7.29", "python-requests/2.28",
                "curl/7.85", "okhttp/4.10", "axios/1.3",
            ]),
        },
        "priority": random.choice(["low", "low", "medium", "medium", "medium", "high", "critical"]),
        "metadata": {
            "session_id": str(uuid.uuid4())[:8],
            "ip_region": random.choice(LOCATIONS[:6]),
        },
    }

    return record


def generate_transaction(
    timestamp: Optional[datetime] = None,
    source_id: Optional[str] = None,
) -> dict[str, Any]:
    """Generate a realistic transaction record."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    if source_id is None:
        source_id = random.choice(TRANSACTION_SOURCES)

    category = random.choice(TRANSACTION_CATEGORIES)

    # Price distributions per category
    price_ranges = {
        "electronics": (50, 2000),
        "clothing": (15, 300),
        "food": (5, 80),
        "software": (10, 500),
        "services": (25, 1000),
        "subscription": (5, 99),
        "refund": (5, 500),
        "hardware": (20, 5000),
        "consulting": (100, 5000),
        "advertising": (50, 10000),
    }

    min_price, max_price = price_ranges.get(category, (10, 500))
    amount = round(random.uniform(min_price, max_price), 2)

    record = {
        "source_id": source_id,
        "record_type": "transaction",
        "amount": amount,
        "currency": random.choice(["USD", "USD", "USD", "EUR", "GBP"]),
        "category": category,
        "timestamp": timestamp.isoformat(),
        "description": f"{category.title()} purchase via {source_id.split('-')[-1]}",
        "metadata": {
            "transaction_id": str(uuid.uuid4()),
            "payment_method": random.choice(["credit_card", "debit_card", "digital_wallet", "bank_transfer"]),
            "customer_segment": random.choice(["retail", "wholesale", "enterprise", "individual"]),
        },
    }

    return record


def generate_batch(
    count: int = 100,
    record_types: Optional[list[str]] = None,
    start_time: Optional[datetime] = None,
    time_spread_minutes: int = 60,
    error_rate: float = 0.02,
) -> list[dict[str, Any]]:
    """
    Generate a batch of mixed records.

    Args:
        count: Number of records to generate
        record_types: Types to include (default: all)
        start_time: Start time for the batch
        time_spread_minutes: Time window for distributing records
        error_rate: Fraction of intentionally malformed records

    Returns:
        List of generated records
    """
    if record_types is None:
        record_types = ["sensor_reading", "api_event", "transaction"]
    if start_time is None:
        start_time = datetime.now(timezone.utc) - timedelta(minutes=time_spread_minutes)

    generators = {
        "sensor_reading": generate_sensor_reading,
        "api_event": generate_api_event,
        "transaction": generate_transaction,
    }

    records = []
    for i in range(count):
        # Distribute timestamps across the time window
        offset = timedelta(minutes=random.uniform(0, time_spread_minutes))
        timestamp = start_time + offset

        record_type = random.choice(record_types)
        gen = generators.get(record_type, generate_sensor_reading)

        record = gen(timestamp=timestamp)

        # Introduce intentional errors for testing
        if random.random() < error_rate:
            error_type = random.choice(["missing_field", "bad_value", "wrong_type"])
            if error_type == "missing_field":
                record.pop("source_id", None)
            elif error_type == "bad_value":
                record["value"] = "not_a_number"
            elif error_type == "wrong_type":
                record["metadata"] = "should_be_dict"

        records.append(record)

    return records


def generate_day_of_data(
    date: Optional[datetime] = None,
    total_records: int = 50000,
    peak_hours: tuple[int, int] = (9, 17),
) -> list[dict[str, Any]]:
    """
    Generate a full day of realistic data with time-of-day patterns.

    Peak hours have ~3x the traffic of off-peak hours.
    """
    if date is None:
        date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    records = []
    # Distribute records across 24 hours with peak pattern
    for hour in range(24):
        # More traffic during peak hours
        is_peak = peak_hours[0] <= hour <= peak_hours[1]
        weight = 3.0 if is_peak else 1.0

        # Calculate records for this hour
        total_weight = sum(3.0 if peak_hours[0] <= h <= peak_hours[1] else 1.0 for h in range(24))
        hour_count = int(total_records * weight / total_weight)

        hour_start = date.replace(hour=hour)
        batch = generate_batch(
            count=hour_count,
            start_time=hour_start,
            time_spread_minutes=60,
        )
        records.extend(batch)

    return records


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate synthetic platform data")
    parser.add_argument("--count", type=int, default=100, help="Number of records")
    parser.add_argument("--type", choices=["sensor_reading", "api_event", "transaction", "mixed"], default="mixed")
    parser.add_argument("--output", type=str, default=None, help="Output file (default: stdout)")
    parser.add_argument("--day", action="store_true", help="Generate a full day of data (~50K records)")

    args = parser.parse_args()

    if args.day:
        data = generate_day_of_data(total_records=args.count if args.count != 100 else 50000)
    else:
        types = [args.type] if args.type != "mixed" else None
        data = generate_batch(count=args.count, record_types=types)

    output = json.dumps(data, indent=2, default=str)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Generated {len(data)} records to {args.output}")
    else:
        print(output[:2000])
        print(f"\n... ({len(data)} total records)")
