# API Reference

## Base URL

**Local**: `http://localhost:5000`
**AWS**: `https://{api-id}.execute-api.{region}.amazonaws.com/{stage}`

## Authentication

API Key required in production (via `x-api-key` header).
Local development has no authentication.

---

## Health

### `GET /health`

Check platform health status.

**Response** `200 OK`
```json
{
  "status": "success",
  "data": {
    "status": "healthy",
    "service": "ingestion-service",
    "stage": "dev",
    "checks": {
      "dynamodb": {"status": "healthy", "tables": 3},
      "event_bus": {"status": "healthy", "topics": 4},
      "memory_mb": 45.2
    }
  }
}
```

---

## Ingestion

### `POST /ingest`

Ingest a single record.

**Request Body**
```json
{
  "source_id": "sensor-temp-001",
  "value": 22.5,
  "unit": "celsius",
  "record_type": "sensor_reading",
  "tags": ["production"],
  "metadata": {
    "firmware": "v2.1"
  }
}
```

**Record Types**: `sensor_reading`, `api_event`, `transaction`

**Supported Units**: `celsius`, `fahrenheit`, `kelvin`, `percent`, `hpa`, `ppm`, `mbps`, `ms`, `count`, `usd`, `eur`, `gbp`

**Response** `201 Created`
```json
{
  "status": "success",
  "data": {
    "event_id": "evt-abc123",
    "source_id": "sensor-temp-001",
    "status": "ingested",
    "timestamp": "2024-01-15T12:00:00Z"
  },
  "message": "Record ingested"
}
```

### `POST /ingest/batch`

Ingest multiple records.

**Request Body**
```json
{
  "records": [
    {"source_id": "s1", "value": 22, "unit": "celsius"},
    {"source_id": "s2", "value": 25, "unit": "celsius"}
  ]
}
```

**Response** `200 OK`
```json
{
  "status": "success",
  "data": {
    "ingested": 2,
    "failed": 0,
    "errors": [],
    "batch_id": "batch-abc123"
  }
}
```

---

## Analytics

### `GET /analytics/dashboard`

Get comprehensive dashboard data.

**Query Parameters**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `period` | string | `24h` | Time period (1h, 6h, 24h, 7d) |

**Response** `200 OK`
```json
{
  "status": "success",
  "data": {
    "overview": {
      "total_records_ingested": 50000,
      "total_records_processed": 49750,
      "total_errors": 250,
      "avg_processing_latency_ms": 12.5
    },
    "category_breakdown": {
      "temperature": {"total_count": 15000},
      "humidity": {"total_count": 10000}
    },
    "service_metrics": { ... },
    "cost_analysis": { ... },
    "recent_records": [ ... ],
    "event_bus": { ... }
  }
}
```

### `GET /analytics/records`

Query processed records.

**Query Parameters**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | `50` | Max records to return |
| `category` | string | — | Filter by category |
| `status` | string | — | Filter by status |

### `GET /analytics/metrics`

Get platform-wide service metrics.

---

## Notifications

### `POST /notify`

Send a notification.

**Request Body**
```json
{
  "title": "Alert Title",
  "message": "Alert details",
  "severity": "warning",
  "source_service": "processing-service"
}
```

**Severity Levels**: `info`, `warning`, `error`, `critical`

### `GET /notifications`

List recent notifications.

**Query Parameters**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | `50` | Max notifications |
| `severity` | string | — | Filter by severity |

---

## Simulation

### `POST /api/simulate`

Run a mini simulation (local server only).

**Request Body**
```json
{
  "count": 500
}
```

---

## Error Responses

All errors follow a consistent format:

```json
{
  "status": "error",
  "error": {
    "code": 422,
    "message": "Validation failed: missing required field 'source_id'"
  },
  "correlation_id": "corr-abc123"
}
```

| Code | Description |
|------|-------------|
| 400 | Bad Request — malformed JSON or missing body |
| 404 | Not Found — endpoint does not exist |
| 422 | Validation Error — schema validation failed |
| 429 | Rate Limited — too many requests |
| 500 | Internal Error — unexpected server error |

## Rate Limits

| Tier | Rate | Burst | Daily Quota |
|------|------|-------|-------------|
| Default | 1000 req/s | 500 | 100,000 |

## CORS

All endpoints return CORS headers:
```
Access-Control-Allow-Origin: *
Access-Control-Allow-Headers: Content-Type, Authorization, X-Correlation-Id
Access-Control-Allow-Methods: GET, POST, OPTIONS
```
