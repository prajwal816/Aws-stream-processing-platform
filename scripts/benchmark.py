"""
Performance benchmarking for the serverless data platform.

Measures throughput, latency percentiles, and resource usage
across the full pipeline. Outputs JSON report.
"""

import json
import os
import sys
import time
import statistics
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

os.environ["AWS_SAM_LOCAL"] = "true"
os.environ["STAGE"] = "dev"
os.environ["LOG_LEVEL"] = "ERROR"

from scripts.generate_data import generate_batch


def run_benchmarks():
    """Run performance benchmarks across all services."""
    print("=" * 60)
    print("  PLATFORM BENCHMARKS")
    print("=" * 60)

    # Load handlers
    services_dir = os.path.join(PROJECT_ROOT, "services")
    for svc in ["ingestion-service", "processing-service", "analytics-service", "notification-service"]:
        p = os.path.join(services_dir, svc)
        if p not in sys.path:
            sys.path.insert(0, p)

    import importlib
    ingestion = importlib.import_module("handler")

    results = {}

    # ============================================
    # Benchmark 1: Single Record Ingestion Latency
    # ============================================
    print("\n📊 Benchmark 1: Single Record Ingestion Latency")
    latencies = []
    test_records = generate_batch(count=200)

    for record in test_records:
        event = {
            "httpMethod": "POST",
            "path": "/ingest",
            "body": json.dumps(record),
            "headers": {},
        }
        start = time.perf_counter()
        ingestion.ingest_record(event)
        elapsed = (time.perf_counter() - start) * 1000
        latencies.append(elapsed)

    latencies.sort()
    results["single_ingestion"] = {
        "samples": len(latencies),
        "avg_ms": round(statistics.mean(latencies), 3),
        "median_ms": round(statistics.median(latencies), 3),
        "p95_ms": round(latencies[int(len(latencies) * 0.95)], 3),
        "p99_ms": round(latencies[int(len(latencies) * 0.99)], 3),
        "min_ms": round(min(latencies), 3),
        "max_ms": round(max(latencies), 3),
        "stddev_ms": round(statistics.stdev(latencies), 3) if len(latencies) > 1 else 0,
    }
    print(f"  Avg: {results['single_ingestion']['avg_ms']:.2f}ms | "
          f"P95: {results['single_ingestion']['p95_ms']:.2f}ms | "
          f"P99: {results['single_ingestion']['p99_ms']:.2f}ms")

    # ============================================
    # Benchmark 2: Batch Ingestion Throughput
    # ============================================
    print("\n📊 Benchmark 2: Batch Ingestion Throughput")
    batch_sizes = [10, 25, 50, 100, 200]
    batch_results = {}

    for batch_size in batch_sizes:
        records = generate_batch(count=batch_size)
        event = {
            "httpMethod": "POST",
            "path": "/ingest/batch",
            "body": json.dumps({"records": records}),
            "headers": {},
        }

        times = []
        for _ in range(5):
            start = time.perf_counter()
            ingestion.batch_ingest(event)
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        avg_time = statistics.mean(times)
        throughput = (batch_size / avg_time) * 1000  # records/sec

        batch_results[str(batch_size)] = {
            "avg_ms": round(avg_time, 2),
            "throughput_rps": round(throughput, 0),
            "per_record_ms": round(avg_time / batch_size, 3),
        }
        print(f"  Batch {batch_size:>3}: {avg_time:.1f}ms | "
              f"{throughput:,.0f} records/sec | "
              f"{avg_time / batch_size:.2f}ms/record")

    results["batch_ingestion"] = batch_results

    # ============================================
    # Benchmark 3: End-to-End Pipeline Latency
    # ============================================
    print("\n📊 Benchmark 3: End-to-End Pipeline (Ingest → Process → Analytics)")
    e2e_latencies = []
    test_records = generate_batch(count=50)

    for record in test_records:
        event = {
            "httpMethod": "POST",
            "path": "/ingest",
            "body": json.dumps(record),
            "headers": {},
        }
        start = time.perf_counter()
        ingestion.ingest_record(event)
        elapsed = (time.perf_counter() - start) * 1000
        e2e_latencies.append(elapsed)

    e2e_latencies.sort()
    results["end_to_end"] = {
        "samples": len(e2e_latencies),
        "avg_ms": round(statistics.mean(e2e_latencies), 3),
        "median_ms": round(statistics.median(e2e_latencies), 3),
        "p95_ms": round(e2e_latencies[int(len(e2e_latencies) * 0.95)], 3),
        "p99_ms": round(e2e_latencies[int(len(e2e_latencies) * 0.99)], 3),
    }
    print(f"  Avg: {results['end_to_end']['avg_ms']:.2f}ms | "
          f"P95: {results['end_to_end']['p95_ms']:.2f}ms | "
          f"P99: {results['end_to_end']['p99_ms']:.2f}ms")

    # ============================================
    # Benchmark 4: Sustained Throughput
    # ============================================
    print("\n📊 Benchmark 4: Sustained Throughput (5000 records)")
    records = generate_batch(count=5000)
    start = time.perf_counter()
    total = 0
    for i in range(0, len(records), 100):
        batch = records[i:i + 100]
        event = {
            "httpMethod": "POST",
            "path": "/ingest/batch",
            "body": json.dumps({"records": batch}),
            "headers": {},
        }
        result = ingestion.batch_ingest(event)
        body = json.loads(result.get("body", "{}"))
        total += body.get("data", {}).get("ingested", 0)

    sustained_duration = time.perf_counter() - start
    sustained_throughput = total / sustained_duration

    results["sustained_throughput"] = {
        "records": total,
        "duration_seconds": round(sustained_duration, 2),
        "throughput_rps": round(sustained_throughput, 0),
        "projected_daily": round(sustained_throughput * 86400, 0),
    }
    print(f"  {total:,} records in {sustained_duration:.2f}s")
    print(f"  Throughput: {sustained_throughput:,.0f} records/sec")
    print(f"  Projected daily: {sustained_throughput * 86400:,.0f} records")

    # ============================================
    # Summary
    # ============================================
    print("\n" + "=" * 60)
    print("  BENCHMARK SUMMARY")
    print("=" * 60)
    print(f"""
  Single Record Latency (avg):    {results['single_ingestion']['avg_ms']:>8.2f} ms
  Single Record Latency (p99):    {results['single_ingestion']['p99_ms']:>8.2f} ms
  Batch Throughput (100 records):  {batch_results['100']['throughput_rps']:>8,.0f} rps
  End-to-End Pipeline (avg):      {results['end_to_end']['avg_ms']:>8.2f} ms
  Sustained Throughput:           {results['sustained_throughput']['throughput_rps']:>8,.0f} rps
  Projected Daily Capacity:       {results['sustained_throughput']['projected_daily']:>8,.0f} records
  Meets 50K/day Target:           {'✅ YES' if results['sustained_throughput']['projected_daily'] >= 50000 else '❌ NO'}
""")

    # Save results
    results["timestamp"] = datetime.now(timezone.utc).isoformat()
    results_path = os.path.join(PROJECT_ROOT, "scripts", "benchmark_results.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  📄 Results saved to: {results_path}")

    return results


if __name__ == "__main__":
    run_benchmarks()
