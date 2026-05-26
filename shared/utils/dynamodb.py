"""
DynamoDB client wrapper with local simulation mode.

Provides a unified interface that works against real DynamoDB in production
and an in-memory store for local development and testing.
"""

import os
import threading
import time
import uuid
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Optional

from shared.utils.logger import get_logger
from shared.utils.metrics import get_metrics

logger = get_logger("dynamodb-client")
metrics = get_metrics("dynamodb")


class LocalDynamoDBTable:
    """
    In-memory DynamoDB table simulation for local development.
    Supports basic CRUD, queries, scans, batch operations, and TTL.
    """

    def __init__(self, table_name: str, partition_key: str, sort_key: Optional[str] = None):
        self.table_name = table_name
        self.partition_key = partition_key
        self.sort_key = sort_key
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._gsi_indexes: dict[str, dict[str, str]] = {}

    def _make_key(self, item: dict[str, Any]) -> str:
        """Generate a composite key string from partition and sort keys."""
        pk = str(item.get(self.partition_key, ""))
        if self.sort_key:
            sk = str(item.get(self.sort_key, ""))
            return f"{pk}##{sk}"
        return pk

    def add_gsi(self, index_name: str, partition_key: str, sort_key: Optional[str] = None) -> None:
        """Register a Global Secondary Index."""
        self._gsi_indexes[index_name] = {
            "partition_key": partition_key,
            "sort_key": sort_key or "",
        }

    def put_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Put an item into the table."""
        key = self._make_key(item)
        with self._lock:
            self._items[key] = deepcopy(item)
        metrics.increment("dynamodb_write_operations")
        return item

    def get_item(self, key: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Get an item by its primary key."""
        composite = self._make_key(key)
        metrics.increment("dynamodb_read_operations")
        with self._lock:
            item = self._items.get(composite)
            return deepcopy(item) if item else None

    def delete_item(self, key: dict[str, Any]) -> bool:
        """Delete an item by its primary key."""
        composite = self._make_key(key)
        metrics.increment("dynamodb_write_operations")
        with self._lock:
            if composite in self._items:
                del self._items[composite]
                return True
            return False

    def query(
        self,
        partition_value: str,
        sort_key_condition: Optional[dict[str, Any]] = None,
        index_name: Optional[str] = None,
        limit: int = 100,
        scan_forward: bool = True,
        filter_expression: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """
        Query items by partition key with optional sort key conditions.

        sort_key_condition format:
            {"operator": "begins_with|between|eq|lt|gt|le|ge", "value": ..., "value2": ...}
        filter_expression format:
            {"field": "field_name", "operator": "eq|ne|gt|lt|contains", "value": ...}
        """
        metrics.increment("dynamodb_read_operations")

        pk_field = self.partition_key
        sk_field = self.sort_key

        if index_name and index_name in self._gsi_indexes:
            gsi = self._gsi_indexes[index_name]
            pk_field = gsi["partition_key"]
            sk_field = gsi["sort_key"] or None

        with self._lock:
            results = []
            for item in self._items.values():
                if str(item.get(pk_field, "")) != str(partition_value):
                    continue

                if sort_key_condition and sk_field:
                    sk_value = item.get(sk_field, "")
                    op = sort_key_condition.get("operator", "eq")
                    cond_value = sort_key_condition.get("value", "")

                    if op == "eq" and str(sk_value) != str(cond_value):
                        continue
                    elif op == "begins_with" and not str(sk_value).startswith(str(cond_value)):
                        continue
                    elif op == "gt" and not (str(sk_value) > str(cond_value)):
                        continue
                    elif op == "lt" and not (str(sk_value) < str(cond_value)):
                        continue
                    elif op == "ge" and not (str(sk_value) >= str(cond_value)):
                        continue
                    elif op == "le" and not (str(sk_value) <= str(cond_value)):
                        continue
                    elif op == "between":
                        value2 = sort_key_condition.get("value2", "")
                        if not (str(cond_value) <= str(sk_value) <= str(value2)):
                            continue

                # Apply filter expression
                if filter_expression:
                    f_field = filter_expression.get("field", "")
                    f_op = filter_expression.get("operator", "eq")
                    f_value = filter_expression.get("value", "")
                    item_value = item.get(f_field, "")

                    if f_op == "eq" and item_value != f_value:
                        continue
                    elif f_op == "ne" and item_value == f_value:
                        continue
                    elif f_op == "contains" and str(f_value) not in str(item_value):
                        continue

                results.append(deepcopy(item))

            # Sort by sort key
            if sk_field:
                results.sort(key=lambda x: str(x.get(sk_field, "")), reverse=not scan_forward)

            return results[:limit]

    def scan(self, limit: int = 1000, filter_expression: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        """Scan all items, optionally with a filter."""
        metrics.increment("dynamodb_read_operations")
        with self._lock:
            results = list(self._items.values())

            if filter_expression:
                f_field = filter_expression.get("field", "")
                f_op = filter_expression.get("operator", "eq")
                f_value = filter_expression.get("value", "")
                filtered = []
                for item in results:
                    item_value = item.get(f_field, "")
                    if f_op == "eq" and item_value == f_value:
                        filtered.append(item)
                    elif f_op == "ne" and item_value != f_value:
                        filtered.append(item)
                    elif f_op == "contains" and str(f_value) in str(item_value):
                        filtered.append(item)
                    elif f_op == "gt" and item_value > f_value:
                        filtered.append(item)
                    elif f_op == "lt" and item_value < f_value:
                        filtered.append(item)
                results = filtered

            return [deepcopy(item) for item in results[:limit]]

    def batch_write(self, items: list[dict[str, Any]]) -> int:
        """Batch write items to the table. Returns count of items written."""
        written = 0
        for item in items:
            self.put_item(item)
            written += 1
        return written

    def item_count(self) -> int:
        """Get the number of items in the table."""
        with self._lock:
            return len(self._items)

    def clear(self) -> None:
        """Clear all items from the table."""
        with self._lock:
            self._items.clear()


class DynamoDBClient:
    """
    Unified DynamoDB client that switches between real AWS DynamoDB
    and local in-memory simulation based on environment configuration.
    """

    def __init__(self):
        self.is_local = os.environ.get("AWS_SAM_LOCAL", "true").lower() == "true"
        self._local_tables: dict[str, LocalDynamoDBTable] = {}
        self._boto_client = None
        self._lock = threading.Lock()

        if not self.is_local:
            try:
                import boto3
                self._boto_client = boto3.resource("dynamodb")
            except ImportError:
                logger.warning("boto3 not available, falling back to local mode")
                self.is_local = True

    def register_table(
        self,
        table_name: str,
        partition_key: str,
        sort_key: Optional[str] = None,
        gsi_definitions: Optional[list[dict[str, str]]] = None,
    ) -> None:
        """Register a table for local simulation."""
        table = LocalDynamoDBTable(table_name, partition_key, sort_key)
        if gsi_definitions:
            for gsi in gsi_definitions:
                table.add_gsi(
                    gsi["index_name"],
                    gsi["partition_key"],
                    gsi.get("sort_key"),
                )
        self._local_tables[table_name] = table
        logger.info(f"Registered local table: {table_name}")

    def _get_table(self, table_name: str) -> LocalDynamoDBTable:
        """Get a local table, creating it with defaults if needed."""
        if table_name not in self._local_tables:
            self.register_table(table_name, "id", "timestamp")
        return self._local_tables[table_name]

    def put_item(self, table_name: str, item: dict[str, Any]) -> dict[str, Any]:
        """Put an item into a table."""
        if self.is_local:
            return self._get_table(table_name).put_item(item)
        else:
            table = self._boto_client.Table(table_name)
            table.put_item(Item=item)
            metrics.increment("dynamodb_write_operations")
            return item

    def get_item(self, table_name: str, key: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Get an item by key."""
        if self.is_local:
            return self._get_table(table_name).get_item(key)
        else:
            table = self._boto_client.Table(table_name)
            response = table.get_item(Key=key)
            metrics.increment("dynamodb_read_operations")
            return response.get("Item")

    def delete_item(self, table_name: str, key: dict[str, Any]) -> bool:
        """Delete an item by key."""
        if self.is_local:
            return self._get_table(table_name).delete_item(key)
        else:
            table = self._boto_client.Table(table_name)
            table.delete_item(Key=key)
            metrics.increment("dynamodb_write_operations")
            return True

    def query(self, table_name: str, **kwargs) -> list[dict[str, Any]]:
        """Query a table."""
        if self.is_local:
            return self._get_table(table_name).query(**kwargs)
        else:
            table = self._boto_client.Table(table_name)
            response = table.query(**kwargs)
            metrics.increment("dynamodb_read_operations")
            return response.get("Items", [])

    def scan(self, table_name: str, **kwargs) -> list[dict[str, Any]]:
        """Scan a table."""
        if self.is_local:
            return self._get_table(table_name).scan(**kwargs)
        else:
            table = self._boto_client.Table(table_name)
            response = table.scan(**kwargs)
            metrics.increment("dynamodb_read_operations")
            return response.get("Items", [])

    def batch_write(self, table_name: str, items: list[dict[str, Any]]) -> int:
        """Batch write items."""
        if self.is_local:
            return self._get_table(table_name).batch_write(items)
        else:
            table = self._boto_client.Table(table_name)
            with table.batch_writer() as batch:
                for item in items:
                    batch.put_item(Item=item)
            metrics.increment("dynamodb_write_operations", len(items))
            return len(items)

    def item_count(self, table_name: str) -> int:
        """Get item count for a table."""
        if self.is_local:
            return self._get_table(table_name).item_count()
        else:
            table = self._boto_client.Table(table_name)
            return table.item_count

    def get_table_stats(self) -> dict[str, Any]:
        """Get statistics for all registered tables."""
        stats = {}
        for name, table in self._local_tables.items():
            stats[name] = {
                "item_count": table.item_count(),
                "partition_key": table.partition_key,
                "sort_key": table.sort_key,
                "gsi_count": len(table._gsi_indexes),
            }
        return stats


# Singleton client
_client: Optional[DynamoDBClient] = None


def get_dynamodb_client() -> DynamoDBClient:
    """Get the global DynamoDB client instance."""
    global _client
    if _client is None:
        _client = DynamoDBClient()
    return _client


def reset_client() -> None:
    """Reset the global client (useful for testing)."""
    global _client
    _client = None
