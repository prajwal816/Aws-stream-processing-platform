# Architecture Documentation

## System Overview

The Cloud-Native Serverless Data Platform is an event-driven analytics system built on AWS serverless services. It ingests, processes, and analyzes streaming data at scale, supporting 50K+ records/day with sub-100ms latency.

## Data Flow

```
1. Client sends data via REST API (API Gateway)
2. Ingestion Service validates, enriches, and stores in RawEvents table
3. Event Bus triggers Processing Service asynchronously
4. Processing Service transforms, filters, aggregates data
5. Processed records stored in ProcessedData table
6. Aggregated summaries stored in AnalyticsSummaries table
7. Analytics Service queries processed data for dashboards
8. Notification Service sends alerts on failures/thresholds
```

## Service Responsibilities

### Ingestion Service
- Input validation (schema, type, range)
- Record enrichment (timestamps, IDs, TTL)
- Batch processing (up to 100 records per batch)
- Event publishing to downstream services
- Health check endpoint

### Processing Service
- Unit normalization (temperature, pressure)
- Category classification (temperature, humidity, financial, network)
- Quality filtering (configurable threshold)
- Deduplication (content-hash based)
- Statistical aggregation (count, sum, min, max, avg)
- Derived metrics computation

### Analytics Service
- Dashboard data aggregation
- Record querying with filters
- Platform-wide metrics
- Category breakdown analysis
- Hourly trend computation
- Cost analysis per service

### Notification Service
- Multi-channel delivery (log, webhook, email)
- Template-based message rendering
- Failure alert handling (dead-letter queue)
- Severity-based routing (info, warning, error, critical)
- Notification history

## DynamoDB Schema Design

### RawEvents Table
- **PK**: `source_id` (String)
- **SK**: `timestamp` (String)
- **GSI**: `event_type-index` (event_type + timestamp)
- **TTL**: `ttl_expiry` (30 days)
- **Access Pattern**: Write-heavy, read for reprocessing

### ProcessedData Table
- **PK**: `record_id` (String)
- **SK**: `processed_at` (String)
- **GSI**: `category-index` (category + processed_at)
- **GSI**: `status-index` (status + processed_at, KEYS_ONLY)
- **TTL**: `ttl_expiry` (90 days)
- **Access Pattern**: Write once, read for analytics

### AnalyticsSummaries Table
- **PK**: `metric_name` (String)
- **SK**: `period` (String)
- **GSI**: `dashboard-index` (category + last_updated)
- **Access Pattern**: Update frequently, read for dashboard

## Event Bus Topics

| Topic | Publisher | Subscriber | Purpose |
|-------|-----------|------------|---------|
| `record.ingested` | Ingestion | Processing | Trigger processing pipeline |
| `processing.completed` | Processing | Notification | Success alerts |
| `processing.failed` | Processing | Notification | Failure alerts |
| `analytics.updated` | Processing | Analytics | Refresh analytics cache |

## Security Model

- **Least-privilege IAM**: Each Lambda has its own role with scoped permissions
- **VPC isolation**: Lambda functions run in private subnets
- **VPC endpoints**: DynamoDB and S3 accessed via gateway endpoints (no internet)
- **Encryption**: DynamoDB SSE, S3 AES-256, API Gateway TLS
- **API throttling**: 1000 req/s steady, 500 burst, 100K/day quota

## Cost Model (50K records/day)

| Service | Monthly Estimate | Notes |
|---------|-----------------|-------|
| Lambda | ~$0.50 | 50K invocations × 256MB × 100ms avg |
| DynamoDB | ~$2.50 | On-demand, ~150K WCU + 100K RCU |
| API Gateway | ~$0.18 | 1.5M requests/month |
| S3 | ~$0.10 | Archive + lifecycle transitions |
| CloudWatch | ~$1.00 | Logs, metrics, alarms |
| VPC/NAT | ~$0.00 | VPC endpoints avoid NAT costs |
| **Total** | **~$4.28/month** | |
