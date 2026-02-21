from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import math
from threading import Lock
from time import monotonic
from typing import DefaultDict, Deque, Dict, Iterable, Tuple
from urllib.parse import unquote


@dataclass(frozen=True)
class ScanGuardDecision:
    allowed: bool
    reason: str = ""
    retry_after_seconds: int = 0


class InMemoryScanGuard:
    DEFAULT_BLOCKED_EXACT_PATHS: Tuple[str, ...] = (
        "/.aws/credentials",
        "/.env",
        "/.env.local",
        "/.env.production",
        "/.git/config",
        "/phpmyadmin",
        "/phpmyadmin/index.php",
        "/server-status",
        "/wp-login.php",
        "/xmlrpc.php",
    )
    DEFAULT_BLOCKED_PREFIXES: Tuple[str, ...] = (
        "/.git/",
        "/.hg/",
        "/.svn/",
        "/boaform/",
        "/cgi-bin/",
        "/mysql/",
        "/phpmyadmin/",
        "/pma/",
        "/vendor/",
        "/wp-admin",
        "/wp-content/",
        "/wp-includes/",
    )
    DEFAULT_BLOCKED_SUBSTRINGS: Tuple[str, ...] = (
        "%2e%2e",
        "../",
        "..\\",
        "/.env",
        "/.git",
        ".bak",
        ".old",
        ".sql",
        "etc/passwd",
        "id_rsa",
    )

    def __init__(
        self,
        *,
        window_seconds: int = 300,
        max_suspicious_hits: int = 8,
        ban_seconds: int = 900,
        blocked_exact_paths: Iterable[str] | None = None,
        blocked_prefixes: Iterable[str] | None = None,
        blocked_substrings: Iterable[str] | None = None,
    ) -> None:
        self.window_seconds = max(1, int(window_seconds))
        self.max_suspicious_hits = max(1, int(max_suspicious_hits))
        self.ban_seconds = max(30, int(ban_seconds))
        self.blocked_exact_paths = self._normalize_path_patterns(
            blocked_exact_paths or self.DEFAULT_BLOCKED_EXACT_PATHS
        )
        self.blocked_prefixes = self._normalize_path_patterns(
            blocked_prefixes or self.DEFAULT_BLOCKED_PREFIXES
        )
        self.blocked_substrings = self._normalize_substring_patterns(
            blocked_substrings or self.DEFAULT_BLOCKED_SUBSTRINGS
        )
        self._lock = Lock()
        self._suspicious_buckets: DefaultDict[str, Deque[float]] = defaultdict(deque)
        self._banned_until: Dict[str, float] = {}

    def inspect(self, *, ip: str, path: str, now: float | None = None) -> ScanGuardDecision:
        checked_at = float(monotonic() if now is None else now)
        ip_value = ip.strip() or "-"

        with self._lock:
            self._prune_bans(checked_at)
            banned_until = self._banned_until.get(ip_value, 0.0)
            if checked_at < banned_until:
                retry_after = max(1, int(math.ceil(banned_until - checked_at)))
                return ScanGuardDecision(
                    allowed=False,
                    reason="ip_temporarily_blocked",
                    retry_after_seconds=retry_after,
                )

            if not self.is_suspicious_path(path):
                return ScanGuardDecision(allowed=True)

            bucket = self._suspicious_buckets[ip_value]
            self._trim(bucket, checked_at)
            bucket.append(checked_at)

            if len(bucket) >= self.max_suspicious_hits:
                banned_until = checked_at + self.ban_seconds
                self._banned_until[ip_value] = banned_until
                bucket.clear()
                return ScanGuardDecision(
                    allowed=False,
                    reason="ip_blocked_after_scan_pattern",
                    retry_after_seconds=self.ban_seconds,
                )

            return ScanGuardDecision(allowed=False, reason="suspicious_scan_path")

    def is_suspicious_path(self, path: str) -> bool:
        normalized = self._normalize_path(path)
        if normalized in self.blocked_exact_paths:
            return True
        for prefix in self.blocked_prefixes:
            if normalized.startswith(prefix):
                return True
        for token in self.blocked_substrings:
            if token in normalized:
                return True
        return False

    @staticmethod
    def _normalize_path(path: str) -> str:
        value = (path or "/").strip().lower()
        if not value.startswith("/"):
            value = f"/{value}"
        try:
            value = unquote(unquote(value))
        except Exception:
            return value
        return value

    @classmethod
    def _normalize_path_patterns(cls, values: Iterable[str]) -> Tuple[str, ...]:
        normalized = []
        for value in values:
            item = cls._normalize_path(value)
            if item and item not in normalized:
                normalized.append(item)
        return tuple(normalized)

    @staticmethod
    def _normalize_substring_patterns(values: Iterable[str]) -> Tuple[str, ...]:
        normalized = []
        for value in values:
            item = value.strip().lower()
            if item and item not in normalized:
                normalized.append(item)
        return tuple(normalized)

    def _prune_bans(self, checked_at: float) -> None:
        expired_ips = [ip for ip, blocked_until in self._banned_until.items() if blocked_until <= checked_at]
        for ip in expired_ips:
            self._banned_until.pop(ip, None)

    def _trim(self, bucket: Deque[float], checked_at: float) -> None:
        min_allowed = checked_at - self.window_seconds
        while bucket and bucket[0] <= min_allowed:
            bucket.popleft()
