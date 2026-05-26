"""
Data transformation logic for the processing pipeline.

Handles normalization, enrichment, field mapping, and categorization
of raw events into processed records.
"""

import math
import hashlib
from datetime import datetime, timezone
from typing import Any


# Unit conversion tables
TEMPERATURE_TO_CELSIUS = {
    "celsius": lambda v: v,
    "fahrenheit": lambda v: (v - 32) * 5 / 9,
    "kelvin": lambda v: v - 273.15,
}

UNIT_NORMALIZATION = {
    "celsius": "celsius",
    "fahrenheit": "celsius",
    "kelvin": "celsius",
    "percent": "percent",
    "ppm": "ppm",
    "hpa": "hpa",
    "ms": "ms",
    "count": "count",
    "bytes": "bytes",
    "mbps": "mbps",
}

# Category classification rules
CATEGORY_RULES = {
    "temperature": {
        "units": ["celsius", "fahrenheit", "kelvin"],
        "thresholds": {"low": 0, "normal": 20, "high": 35, "critical": 50},
    },
    "humidity": {
        "units": ["percent"],
        "keywords": ["humidity", "moisture", "rh"],
        "thresholds": {"low": 20, "normal": 40, "high": 70, "critical": 90},
    },
    "pressure": {
        "units": ["hpa"],
        "thresholds": {"low": 980, "normal": 1013, "high": 1040, "critical": 1060},
    },
    "air_quality": {
        "units": ["ppm"],
        "thresholds": {"good": 0, "moderate": 50, "unhealthy": 100, "hazardous": 300},
    },
    "network": {
        "units": ["mbps", "ms"],
        "keywords": ["latency", "bandwidth", "throughput"],
    },
    "financial": {
        "record_types": ["transaction"],
        "keywords": ["amount", "payment", "transfer"],
    },
}


class DataTransformer:
    """
    Transforms raw event data into normalized, enriched processed records.

    Pipeline:
    1. Normalize units
    2. Classify category
    3. Calculate derived metrics
    4. Enrich with metadata
    5. Compute quality adjustments
    """

    def __init__(self):
        self.transformations_log: list[str] = []

    def transform(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """
        Apply the full transformation pipeline to a raw event.

        Returns a dict with transformed fields and metadata.
        """
        self.transformations_log = []
        result = dict(raw_data)

        # Step 1: Normalize units
        result = self._normalize_units(result)

        # Step 2: Classify category
        result = self._classify_category(result)

        # Step 3: Calculate derived metrics
        result = self._calculate_derived_metrics(result)

        # Step 4: Enrich with metadata
        result = self._enrich_metadata(result)

        # Step 5: Quality adjustment
        result = self._adjust_quality(result)

        result["transformations"] = list(self.transformations_log)
        return result

    def _normalize_units(self, data: dict[str, Any]) -> dict[str, Any]:
        """Normalize values to standard units."""
        unit = data.get("unit", "count").lower()
        value = float(data.get("value", 0))

        # Temperature normalization to Celsius
        if unit in TEMPERATURE_TO_CELSIUS:
            converter = TEMPERATURE_TO_CELSIUS[unit]
            normalized = converter(value)
            data["normalized_value"] = round(normalized, 4)
            data["normalized_unit"] = "celsius"
            if unit != "celsius":
                self.transformations_log.append(f"unit_conversion:{unit}->celsius")
        else:
            data["normalized_value"] = value
            data["normalized_unit"] = UNIT_NORMALIZATION.get(unit, unit)

        self.transformations_log.append("unit_normalization")
        return data

    def _classify_category(self, data: dict[str, Any]) -> dict[str, Any]:
        """Classify the record into a category based on unit and content."""
        unit = data.get("unit", "count").lower()
        record_type = data.get("record_type", "sensor_reading")
        source_id = data.get("source_id", "").lower()

        # Check each category rule
        for category, rules in CATEGORY_RULES.items():
            # Match by record type
            if "record_types" in rules and record_type in rules["record_types"]:
                data["category"] = category
                self.transformations_log.append(f"categorized:{category}")
                return data

            # Match by unit
            if "units" in rules and unit in rules["units"]:
                data["category"] = category

                # Sub-classify by threshold
                if "thresholds" in rules:
                    value = data.get("normalized_value", data.get("value", 0))
                    thresholds = rules["thresholds"]
                    level = "unknown"
                    for level_name, threshold in sorted(thresholds.items(), key=lambda x: x[1], reverse=True):
                        if value >= threshold:
                            level = level_name
                            break
                    data["threshold_level"] = level
                    data["enrichment"] = data.get("enrichment", {})
                    data["enrichment"]["threshold_level"] = level

                self.transformations_log.append(f"categorized:{category}")
                return data

            # Match by keywords
            if "keywords" in rules:
                for kw in rules["keywords"]:
                    if kw in source_id or kw in str(data.get("metadata", {})).lower():
                        data["category"] = category
                        self.transformations_log.append(f"categorized:{category}")
                        return data

        # Default category
        data["category"] = data.get("category", "general")
        self.transformations_log.append("categorized:general")
        return data

    def _calculate_derived_metrics(self, data: dict[str, Any]) -> dict[str, Any]:
        """Calculate additional derived metrics from the data."""
        enrichment = data.get("enrichment", {})
        value = data.get("normalized_value", data.get("value", 0))

        # Z-score simulation (would use historical data in production)
        enrichment["magnitude"] = abs(value)
        enrichment["is_negative"] = value < 0
        enrichment["log_value"] = round(math.log1p(abs(value)), 4) if value != 0 else 0

        # Time-based enrichment
        timestamp = data.get("timestamp", "")
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                enrichment["hour_of_day"] = dt.hour
                enrichment["day_of_week"] = dt.strftime("%A")
                enrichment["is_business_hours"] = 9 <= dt.hour <= 17
                enrichment["time_period"] = (
                    "morning" if 6 <= dt.hour < 12
                    else "afternoon" if 12 <= dt.hour < 18
                    else "evening" if 18 <= dt.hour < 22
                    else "night"
                )
            except (ValueError, AttributeError):
                pass

        data["enrichment"] = enrichment
        self.transformations_log.append("derived_metrics")
        return data

    def _enrich_metadata(self, data: dict[str, Any]) -> dict[str, Any]:
        """Add processing metadata to the record."""
        enrichment = data.get("enrichment", {})

        # Data fingerprint
        fingerprint_source = f"{data.get('source_id', '')}:{data.get('normalized_value', '')}:{data.get('category', '')}"
        enrichment["fingerprint"] = hashlib.md5(fingerprint_source.encode()).hexdigest()[:12]

        # Processing metadata
        enrichment["processed_at"] = datetime.now(timezone.utc).isoformat()
        enrichment["processor_version"] = "1.0.0"

        data["enrichment"] = enrichment
        self.transformations_log.append("metadata_enrichment")
        return data

    def _adjust_quality(self, data: dict[str, Any]) -> dict[str, Any]:
        """Adjust quality score based on data completeness and validity."""
        quality = float(data.get("quality_score", 1.0))

        # Boost quality for records with rich metadata
        if data.get("metadata") and len(data["metadata"]) > 2:
            quality = min(1.0, quality * 1.02)

        # Boost for tagged records
        if data.get("tags") and len(data["tags"]) > 0:
            quality = min(1.0, quality * 1.01)

        # Penalize for outlier values
        value = abs(data.get("normalized_value", 0))
        if value > 10000:
            quality *= 0.9

        data["quality_score"] = round(quality, 4)
        self.transformations_log.append("quality_adjustment")
        return data
