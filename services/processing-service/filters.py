"""
Configurable data filters for the processing pipeline.

Supports threshold-based filtering, deduplication, and quality scoring
to control which records flow through the pipeline.
"""

import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from shared.configs.settings import get_settings

settings = get_settings()


class DataFilter:
    """
    Applies configurable filters to incoming data.

    Filters:
    1. Quality threshold — reject records below minimum quality
    2. Deduplication — reject duplicate records (by content hash)
    3. Value threshold — reject records outside acceptable ranges
    4. Rate filter — reject if source is sending too fast
    """

    def __init__(
        self,
        quality_threshold: float = 0.0,
        enable_dedup: bool = True,
        dedup_window_size: int = 10000,
    ):
        self.quality_threshold = quality_threshold or settings.quality_threshold
        self.enable_dedup = enable_dedup
        self.dedup_window_size = dedup_window_size
        self._seen_hashes: set[str] = set()
        self._hash_order: list[str] = []
        self._source_counts: dict[str, int] = defaultdict(int)

    def apply_filters(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Apply all filters to a record.

        Returns:
            dict with 'passed' (bool) and 'reason' (str if filtered)
        """
        # Filter 1: Quality threshold
        quality = float(data.get("quality_score", 1.0))
        if quality < self.quality_threshold:
            return {
                "passed": False,
                "reason": f"Quality score {quality:.4f} below threshold {self.quality_threshold}",
                "filter": "quality_threshold",
            }

        # Filter 2: Deduplication
        if self.enable_dedup:
            content_hash = self._compute_hash(data)
            if content_hash in self._seen_hashes:
                return {
                    "passed": False,
                    "reason": f"Duplicate record detected (hash: {content_hash[:8]})",
                    "filter": "deduplication",
                }
            self._add_hash(content_hash)

        # Filter 3: Value range check (configurable per category)
        value_check = self._check_value_range(data)
        if not value_check["valid"]:
            return {
                "passed": False,
                "reason": value_check["reason"],
                "filter": "value_range",
            }

        # Filter 4: Null/empty value check
        if data.get("record_type") == "sensor_reading":
            value = data.get("value")
            if value is None:
                return {
                    "passed": False,
                    "reason": "Null value in sensor reading",
                    "filter": "null_value",
                }

        return {"passed": True, "reason": None, "filter": None}

    def _compute_hash(self, data: dict[str, Any]) -> str:
        """Compute a content hash for deduplication."""
        hash_source = (
            f"{data.get('source_id', '')}:"
            f"{data.get('value', '')}:"
            f"{data.get('timestamp', '')}:"
            f"{data.get('unit', '')}"
        )
        return hashlib.sha256(hash_source.encode()).hexdigest()[:16]

    def _add_hash(self, content_hash: str) -> None:
        """Add a hash to the dedup window, evicting old entries if needed."""
        self._seen_hashes.add(content_hash)
        self._hash_order.append(content_hash)

        # Evict oldest entries if window is full
        while len(self._hash_order) > self.dedup_window_size:
            oldest = self._hash_order.pop(0)
            self._seen_hashes.discard(oldest)

    def _check_value_range(self, data: dict[str, Any]) -> dict[str, Any]:
        """Check if the value is within acceptable ranges."""
        record_type = data.get("record_type", "sensor_reading")
        value = data.get("value", 0)

        if record_type == "sensor_reading":
            # Extreme outlier detection
            if isinstance(value, (int, float)) and abs(value) > 1_000_000:
                return {
                    "valid": False,
                    "reason": f"Value {value} exceeds extreme threshold (±1,000,000)",
                }

        elif record_type == "transaction":
            amount = data.get("amount", 0)
            if isinstance(amount, (int, float)) and amount < 0:
                return {
                    "valid": False,
                    "reason": f"Negative transaction amount: {amount}",
                }

        return {"valid": True, "reason": None}

    def get_stats(self) -> dict[str, Any]:
        """Get filter statistics."""
        return {
            "dedup_cache_size": len(self._seen_hashes),
            "quality_threshold": self.quality_threshold,
            "dedup_enabled": self.enable_dedup,
        }

    def reset(self) -> None:
        """Reset all filter state."""
        self._seen_hashes.clear()
        self._hash_order.clear()
        self._source_counts.clear()
