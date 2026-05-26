"""
Full pipeline simulation engine.

Generates 50K+ synthetic records and runs them through the entire
ingestion → processing → analytics → notification pipeline locally.
Produces benchmark metrics and a summary report.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

os.environ["AWS_SAM_LOCAL"] = "true"
os.environ["STAGE"] = "dev"
os.environ["LOG_LEVEL"] = "WARNING"  # Reduce noise during simulation

from shared.utils.logger import get_logger
from shared.utils.metrics import get_metrics, get_all_metrics
from shared.utils.event_bus import get_event_bus, Topics
from shared.configs.settings import get_settings
from scripts.generate_data import generate_batch, generate_day_of_data


logger = get_logger("simulator")
settings = get_settings()


def import_handlers():
    """Import all service handlers."""
    ingestion_dir = os.path.join(PROJECT_ROOT, "services", "ingestion-service")
    processing_dir = os.path.join(PROJECT_ROOT, "services", "processing-service")
    analytics_dir = os.path.join(PROJECT_ROOT, "services", "analytics-service")
    notification_dir = os.path.join(PROJECT_ROOT, "services", "notification-service")

    for d in [ingestion_dir, processing_dir, analytics_dir, notification_dir]:
        if d not in sys.path:
            sys.path.insert(0, d)

    # Import handlers
    import importlib
    sys.path.insert(0, ingestion_dir)
    ingestion_handler = importlib.import_module("handler")

    sys.path.insert(0, processing_dir)
    # Need to reload to pick up the right modules
    processing_handler_mod = importlib.import_module("handler")

    sys.path.insert(0, analytics_dir)
    analytics_handler_mod = importlib.import_module("handler")

    sys.path.insert(0, notification_dir)
    notification_handler_mod = importlib.import_module("handler")

    return {
        "ingestion": ingestion_handler,
        "processing": processing_handler_mod,
        "analytics": analytics_handler_mod,
        "notification": notification_handler_mod,
    }


def run_simulation(record_count: int = 50000, batch_size: int = 100):
    """
    Run the full pipeline simulation.

    Args:
        record_count: Total records to process
        batch_size: Records per batch
    """
    print("=" * 70)
    print("  CLOUD-NATIVE SERVERLESS DATA PLATFORM — SIMULATION ENGINE")
    print("=" * 70)
    print(f"\n  Target Records:    {record_count:,}")
    print(f"  Batch Size:        {batch_size}")
    print(f"  Start Time:        {datetime.now(timezone.utc).isoformat()}")
    print(f"  Environment:       {settings.stage}")
    print("=" * 70)

    # Import handlers
    print("\n⏳ Loading service handlers...")
    handlers = import_handlers()
    print("  ✓ All services loaded")

    # Wire up event bus for processing pipeline
    event_bus = get_event_bus()

    # Subscribe processing service to ingestion events
    def process_ingested_record(message):
        """Process a record that was just ingested."""
        event = {"data": message.get("data", message)}
        handlers["processing"].process_event(event)

    def handle_processing_complete(message):
        """Handle processing completion notification."""
        handlers["notification"].handle_notification(message)

    def handle_processing_failure(message):
        """Handle processing failure notification."""
        handlers["notification"].handle_failure(message)

    event_bus.subscribe(Topics.RECORD_INGESTED, process_ingested_record)
    event_bus.subscribe(Topics.PROCESSING_COMPLETED, handle_processing_complete)
    event_bus.subscribe(Topics.PROCESSING_FAILED, handle_processing_failure)

    print("  ✓ Event bus wired up")

    # Generate data
    print(f"\n⏳ Generating {record_count:,} synthetic records...")
    gen_start = time.time()
    all_records = generate_day_of_data(total_records=record_count)
    gen_duration = time.time() - gen_start
    print(f"  ✓ Generated {len(all_records):,} records in {gen_duration:.2f}s")

    # Process records in batches
    print(f"\n🚀 Starting pipeline simulation...")
    sim_start = time.time()
    total_ingested = 0
    total_failed = 0
    batch_count = 0
    progress_interval = max(1, record_count // 20)

    for i in range(0, len(all_records), batch_size):
        batch = all_records[i:i + batch_size]
        batch_count += 1

        # Ingest batch
        event = {
            "httpMethod": "POST",
            "path": "/ingest/batch",
            "body": json.dumps({"records": batch}),
            "headers": {},
        }

        try:
            result = handlers["ingestion"].batch_ingest(event)
            result_body = json.loads(result.get("body", "{}"))
            data = result_body.get("data", {})
            ingested = data.get("ingested", 0)
            failed = data.get("failed", 0)
            total_ingested += ingested
            total_failed += failed
        except Exception as e:
            total_failed += len(batch)
            logger.error(f"Batch {batch_count} failed: {str(e)}")

        # Progress update
        processed_so_far = i + len(batch)
        if processed_so_far % progress_interval < batch_size:
            pct = (processed_so_far / len(all_records)) * 100
            elapsed = time.time() - sim_start
            rate = processed_so_far / elapsed if elapsed > 0 else 0
            print(f"  📊 Progress: {pct:5.1f}% | {processed_so_far:,}/{len(all_records):,} | "
                  f"{rate:,.0f} records/sec | Elapsed: {elapsed:.1f}s")

    sim_duration = time.time() - sim_start
    throughput = total_ingested / sim_duration if sim_duration > 0 else 0

    # Get final metrics
    print("\n⏳ Computing final analytics...")
    analytics_event = {
        "httpMethod": "GET",
        "path": "/analytics/dashboard",
        "queryStringParameters": {},
        "headers": {},
    }
    dashboard_result = handlers["analytics"].get_dashboard_data(analytics_event)
    dashboard_data = json.loads(dashboard_result.get("body", "{}")).get("data", {})

    # Get cost estimates
    all_metrics = get_all_metrics()
    total_cost = 0
    for svc_name, collector in all_metrics.items():
        cost = collector.get_cost_estimate()
        total_cost += cost.get("total_estimated_cost", 0)

    # Print results
    print("\n" + "=" * 70)
    print("  SIMULATION RESULTS")
    print("=" * 70)
    print(f"""
  📈 Pipeline Performance
  ─────────────────────────────────────
  Total Records Generated:    {len(all_records):>10,}
  Records Ingested:           {total_ingested:>10,}
  Records Failed:             {total_failed:>10,}
  Success Rate:               {(total_ingested / max(len(all_records), 1) * 100):>9.2f}%
  Batches Processed:          {batch_count:>10,}

  ⏱️  Throughput & Latency
  ─────────────────────────────────────
  Simulation Duration:        {sim_duration:>10.2f}s
  Throughput:                 {throughput:>10,.0f} records/sec
  Projected Daily Capacity:   {throughput * 86400:>10,.0f} records/day

  💰 Cost Estimation (On-Demand)
  ─────────────────────────────────────
  Estimated Cost (this run):  ${total_cost:>9.4f}
  Projected Daily Cost:       ${total_cost * (50000 / max(total_ingested, 1)):>9.4f}
  Projected Monthly Cost:     ${total_cost * (50000 / max(total_ingested, 1)) * 30:>9.4f}
""")

    # Service-level metrics
    print("  📊 Service Metrics")
    print("  ─────────────────────────────────────")
    for svc_name, collector in all_metrics.items():
        summary = collector.get_summary()
        counters = summary.get("counters", {})
        print(f"  {svc_name}:")
        for key, val in sorted(counters.items()):
            if val > 0:
                print(f"    {key}: {val:,.0f}")

    # Event bus stats
    event_stats = event_bus.get_stats()
    print(f"\n  📡 Event Bus")
    print(f"  ─────────────────────────────────────")
    print(f"  Total Events:       {event_stats['total_events']:,}")
    print(f"  Dead Letter Queue:  {event_stats['dlq_size']}")
    for topic, count in event_stats.get("topics", {}).items():
        print(f"    {topic}: {count:,}")

    print("\n" + "=" * 70)
    print("  ✅ SIMULATION COMPLETE")
    print("=" * 70)

    # Save results to JSON
    results = {
        "simulation_time": datetime.now(timezone.utc).isoformat(),
        "records_generated": len(all_records),
        "records_ingested": total_ingested,
        "records_failed": total_failed,
        "success_rate": round(total_ingested / max(len(all_records), 1) * 100, 2),
        "duration_seconds": round(sim_duration, 2),
        "throughput_per_second": round(throughput, 0),
        "projected_daily_capacity": round(throughput * 86400, 0),
        "estimated_cost": round(total_cost, 6),
        "service_metrics": {
            name: collector.get_summary()
            for name, collector in all_metrics.items()
        },
        "cost_breakdown": {
            name: collector.get_cost_estimate()
            for name, collector in all_metrics.items()
        },
        "event_bus_stats": event_stats,
        "dashboard_data": dashboard_data,
    }

    results_path = os.path.join(PROJECT_ROOT, "scripts", "simulation_results.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  📄 Results saved to: {results_path}")

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run platform simulation")
    parser.add_argument("--count", type=int, default=50000, help="Number of records to simulate")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for ingestion")
    args = parser.parse_args()

    run_simulation(record_count=args.count, batch_size=args.batch_size)
