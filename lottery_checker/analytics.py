from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from threading import Lock
from time import time
from typing import Any, Callable, Deque, Dict, List
import os
import uuid

try:
    import boto3
    from boto3.dynamodb.conditions import Key
    from botocore.exceptions import BotoCoreError, ClientError
except Exception:  # pragma: no cover - optional dependency fallback
    boto3 = None  # type: ignore[assignment]

    class BotoCoreError(Exception):
        pass

    class ClientError(Exception):
        pass

    def Key(value: str) -> str:  # type: ignore[no-redef]
        return value


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


LOGGER = logging.getLogger(__name__)


@dataclass
class RequestRecord:
    timestamp: str
    epoch_seconds: int
    method: str
    path: str
    status_code: int
    ip: str
    duration_ms: int


class TrafficTracker:
    def __init__(
        self,
        max_recent: int = 300,
        refresh_window_seconds: int = 15,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self._lock = Lock()
        self._total_requests = 0
        self._path_counter: Counter[str] = Counter()
        self._status_counter: Counter[int] = Counter()
        self._recent_requests: Deque[RequestRecord] = deque(maxlen=max_recent)
        self._refresh_window_seconds = max(1, refresh_window_seconds)
        self._last_navigation_hits: Dict[str, float] = {}
        self._now_fn = now_fn or time

    def _is_static_path(self, path: str) -> bool:
        return path.startswith("/static/") or path in {"/favicon.ico"}

    def _is_excluded_path(self, path: str) -> bool:
        # Exclude admin and health checks from analytics to avoid self-observing noise.
        return path.startswith("/admin") or path == "/health"

    def _is_page_view(self, method: str, accept: str) -> bool:
        if method != "GET":
            return False
        return "text/html" in accept.lower()

    def _is_refresh_duplicate(
        self,
        *,
        method: str,
        path: str,
        ip: str,
        user_agent: str,
        accept: str,
        now_epoch: float,
    ) -> bool:
        if not self._is_page_view(method, accept):
            return False
        if path == "/health":
            return False

        key = f"{ip}|{user_agent[:120]}|{path}"
        last_hit = self._last_navigation_hits.get(key)
        self._last_navigation_hits[key] = now_epoch
        if last_hit is None:
            return False
        return (now_epoch - last_hit) <= self._refresh_window_seconds

    def _prune_navigation_cache(self, now_epoch: float) -> None:
        threshold = now_epoch - (self._refresh_window_seconds * 4)
        stale_keys = [key for key, hit_ts in self._last_navigation_hits.items() if hit_ts < threshold]
        for key in stale_keys:
            self._last_navigation_hits.pop(key, None)

    def record(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        ip: str,
        duration_ms: int,
        accept: str = "",
        user_agent: str = "",
    ) -> RequestRecord | None:
        with self._lock:
            now_epoch = self._now_fn()
            if self._is_static_path(path) or self._is_excluded_path(path):
                return None
            if self._is_refresh_duplicate(
                method=method,
                path=path,
                ip=ip,
                user_agent=user_agent,
                accept=accept,
                now_epoch=now_epoch,
            ):
                return None

            self._prune_navigation_cache(now_epoch)
            self._total_requests += 1
            self._path_counter[path] += 1
            self._status_counter[status_code] += 1
            request_record = RequestRecord(
                timestamp=utc_now().isoformat(),
                epoch_seconds=int(now_epoch),
                method=method,
                path=path,
                status_code=status_code,
                ip=ip,
                duration_ms=duration_ms,
            )
            self._recent_requests.appendleft(request_record)
            return request_record

    def snapshot(self, top_paths: int = 10, recent_limit: int = 50, series_minutes: int = 30) -> Dict[str, Any]:
        with self._lock:
            now_epoch = int(self._now_fn())
            minute_counts: Dict[int, int] = {}
            for row in self._recent_requests:
                minute_bucket = (row.epoch_seconds // 60) * 60
                minute_counts[minute_bucket] = minute_counts.get(minute_bucket, 0) + 1

            minute_series = []
            range_start = ((now_epoch - (series_minutes - 1) * 60) // 60) * 60
            for minute_epoch in range(range_start, now_epoch + 1, 60):
                minute_label = datetime.fromtimestamp(minute_epoch, tz=timezone.utc).strftime("%H:%M")
                minute_series.append({"minute": minute_label, "count": minute_counts.get(minute_epoch, 0)})

            return {
                "total_requests": self._total_requests,
                "top_paths": self._path_counter.most_common(top_paths),
                "status_counts": sorted(self._status_counter.items(), key=lambda item: item[0]),
                "recent_requests": list(self._recent_requests)[:recent_limit],
                "minute_series": minute_series,
            }


class DynamoSearchHistoryStore:
    SEARCH_PARTITION = "SEARCH"
    TRAFFIC_PARTITION = "TRAFFIC"

    def __init__(
        self,
        table_name: str,
        region_name: str,
        ttl_days: int = 30,
        traffic_ttl_days: int | None = None,
    ) -> None:
        if boto3 is None:
            raise RuntimeError("boto3 is required for DynamoDB integration")
        self.table_name = table_name
        self.ttl_days = ttl_days
        self.traffic_ttl_days = max(1, int(traffic_ttl_days or ttl_days))
        self._dynamodb = boto3.resource("dynamodb", region_name=region_name)
        self._table = self._dynamodb.Table(table_name)
        self._enabled = True
        self._last_error = ""

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def last_error(self) -> str:
        return self._last_error

    def _disable(self, exc: Exception, context: str) -> None:
        self._enabled = False
        self._last_error = f"{type(exc).__name__}: {exc}"
        LOGGER.warning("DynamoDB %s disabled: %s", context, self._last_error)

    def save_search(
        self,
        *,
        mode: str,
        game: str,
        draw_number: str,
        summary: str,
        ticket_count: int,
        winning_count: int,
        client_ip: str,
        user_agent: str,
    ) -> None:
        if not self._enabled:
            return

        now = utc_now()
        epoch_seconds = int(now.timestamp())
        epoch_millis = int(now.timestamp() * 1000)
        ttl_epoch = epoch_seconds + self.ttl_days * 24 * 60 * 60

        item = {
            "pk": self.SEARCH_PARTITION,
            "sk": f"{epoch_millis:013d}#{uuid.uuid4().hex[:10]}",
            "created_at": epoch_seconds,
            "created_at_iso": now.isoformat(),
            "ttl_epoch": ttl_epoch,
            "mode": mode,
            "game": game,
            "draw_number": draw_number,
            "summary": summary,
            "ticket_count": ticket_count,
            "winning_count": winning_count,
            "client_ip": client_ip[:64],
            "user_agent": user_agent[:512],
        }

        try:
            self._table.put_item(Item=item)
        except (ClientError, BotoCoreError) as exc:
            self._disable(exc, "search history")

    def list_recent_searches(self, limit: int = 100) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        try:
            response = self._table.query(
                KeyConditionExpression=Key("pk").eq(self.SEARCH_PARTITION),
                ScanIndexForward=False,
                Limit=max(1, min(limit, 200)),
            )
        except (ClientError, BotoCoreError) as exc:
            self._disable(exc, "search history")
            return []

        items = response.get("Items", [])
        return items if isinstance(items, list) else []

    @staticmethod
    def _item_int(item: Dict[str, Any], key: str, default: int = 0) -> int:
        try:
            return int(item.get(key, default))
        except Exception:
            return default

    @staticmethod
    def _item_str(item: Dict[str, Any], key: str, default: str = "") -> str:
        value = item.get(key, default)
        return str(value) if value is not None else default

    def save_traffic_event(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        ip: str,
        duration_ms: int,
        epoch_seconds: int | None = None,
    ) -> None:
        if not self._enabled:
            return

        created_epoch = int(epoch_seconds) if epoch_seconds is not None else int(time())
        ttl_epoch = created_epoch + self.traffic_ttl_days * 24 * 60 * 60
        created_iso = datetime.fromtimestamp(created_epoch, tz=timezone.utc).isoformat()
        epoch_millis = int(created_epoch * 1000)

        item = {
            "pk": self.TRAFFIC_PARTITION,
            "sk": f"{epoch_millis:013d}#{uuid.uuid4().hex[:10]}",
            "created_at": created_epoch,
            "created_at_iso": created_iso,
            "ttl_epoch": ttl_epoch,
            "method": method[:10],
            "path": path[:256],
            "status_code": int(status_code),
            "client_ip": ip[:64],
            "duration_ms": max(0, int(duration_ms)),
        }

        try:
            self._table.put_item(Item=item)
        except (ClientError, BotoCoreError) as exc:
            self._disable(exc, "traffic history")

    def _list_recent_traffic_events(self, limit: int, lookback_minutes: int) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []

        threshold_epoch = int(time()) - max(1, lookback_minutes) * 60
        items: List[Dict[str, Any]] = []
        exclusive_start_key = None
        remaining = max(1, min(limit, 2000))

        while remaining > 0:
            query_kwargs: Dict[str, Any] = {
                "KeyConditionExpression": Key("pk").eq(self.TRAFFIC_PARTITION),
                "ScanIndexForward": False,
                "Limit": min(200, remaining),
            }
            if exclusive_start_key:
                query_kwargs["ExclusiveStartKey"] = exclusive_start_key

            try:
                response = self._table.query(**query_kwargs)
            except (ClientError, BotoCoreError) as exc:
                self._disable(exc, "traffic history")
                return []

            page_items = response.get("Items", [])
            if not isinstance(page_items, list) or not page_items:
                break

            reached_old_item = False
            for item in page_items:
                created_at = self._item_int(item, "created_at", 0)
                if created_at < threshold_epoch:
                    reached_old_item = True
                    break
                items.append(item)
                remaining -= 1
                if remaining <= 0:
                    break

            if reached_old_item or remaining <= 0:
                break

            exclusive_start_key = response.get("LastEvaluatedKey")
            if not exclusive_start_key:
                break

        return items

    def build_traffic_snapshot(
        self,
        *,
        top_paths: int = 10,
        recent_limit: int = 50,
        series_minutes: int = 30,
        lookback_minutes: int = 1440,
    ) -> Dict[str, Any]:
        now_epoch = int(time())
        items = self._list_recent_traffic_events(limit=2000, lookback_minutes=lookback_minutes)

        path_counter: Counter[str] = Counter()
        status_counter: Counter[int] = Counter()
        recent_requests: List[RequestRecord] = []
        minute_counts: Dict[int, int] = {}
        series_start_epoch = now_epoch - (max(1, series_minutes) - 1) * 60

        for item in items:
            created_epoch = self._item_int(item, "created_at", 0)
            path_value = self._item_str(item, "path", "")
            status_value = self._item_int(item, "status_code", 0)
            method_value = self._item_str(item, "method", "GET")
            ip_value = self._item_str(item, "client_ip", "-")
            duration_value = self._item_int(item, "duration_ms", 0)
            created_iso = self._item_str(item, "created_at_iso", "")

            path_counter[path_value] += 1
            status_counter[status_value] += 1
            if created_epoch >= series_start_epoch:
                minute_bucket = (created_epoch // 60) * 60
                minute_counts[minute_bucket] = minute_counts.get(minute_bucket, 0) + 1

            if len(recent_requests) < max(1, recent_limit):
                recent_requests.append(
                    RequestRecord(
                        timestamp=created_iso,
                        epoch_seconds=created_epoch,
                        method=method_value,
                        path=path_value,
                        status_code=status_value,
                        ip=ip_value,
                        duration_ms=duration_value,
                    )
                )

        minute_series = []
        range_start = ((now_epoch - (max(1, series_minutes) - 1) * 60) // 60) * 60
        for minute_epoch in range(range_start, now_epoch + 1, 60):
            minute_label = datetime.fromtimestamp(minute_epoch, tz=timezone.utc).strftime("%H:%M")
            minute_series.append({"minute": minute_label, "count": minute_counts.get(minute_epoch, 0)})

        return {
            "total_requests": len(items),
            "top_paths": path_counter.most_common(top_paths),
            "status_counts": sorted(status_counter.items(), key=lambda item: item[0]),
            "recent_requests": recent_requests[:recent_limit],
            "minute_series": minute_series,
        }


def create_search_store_from_env() -> DynamoSearchHistoryStore | None:
    if boto3 is None:
        return None

    table_name = os.environ.get("DYNAMODB_SEARCH_TABLE", "").strip()
    if not table_name:
        return None

    region_name = os.environ.get("AWS_REGION", "").strip() or os.environ.get("AWS_DEFAULT_REGION", "").strip()
    if not region_name:
        region_name = "ap-northeast-1"

    ttl_days_raw = os.environ.get("SEARCH_HISTORY_TTL_DAYS", "").strip()
    try:
        ttl_days = int(ttl_days_raw) if ttl_days_raw else 30
    except ValueError:
        ttl_days = 30

    traffic_ttl_days_raw = os.environ.get("TRAFFIC_HISTORY_TTL_DAYS", "").strip()
    try:
        traffic_ttl_days = int(traffic_ttl_days_raw) if traffic_ttl_days_raw else ttl_days
    except ValueError:
        traffic_ttl_days = ttl_days

    try:
        return DynamoSearchHistoryStore(
            table_name=table_name,
            region_name=region_name,
            ttl_days=max(1, ttl_days),
            traffic_ttl_days=max(1, traffic_ttl_days),
        )
    except Exception:
        return None
