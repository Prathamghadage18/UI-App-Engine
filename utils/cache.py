"""
Lightweight in-memory TTL cache for the SCADA dashboard API.

Why caching?
────────────
The frontend polls three endpoints at different intervals:
  • /api/shifts/{machine}   → every  5 s
  • /api/snapshot/{machine} → every 15 s
  • /api/weekly/{machine}   → every 30 min

Without caching, every poll triggers expensive InfluxDB Flux queries
(range scans, aggregations, deltas). Since the underlying sensor data
only changes every few seconds, most of those queries return the same
result.  A short-lived TTL cache eliminates redundant work while
keeping the dashboard data fresh.

Design notes
────────────
• Pure-Python dict + time.time() — zero dependencies.
• Thread-safe enough for a single-process uvicorn worker.
  For multi-worker deployments, swap this module with a Redis
  adapter that exposes the same get / set / invalidate interface.
• Lazy expiry: stale entries are detected on read and pruned
  periodically to prevent unbounded memory growth.
"""

import time
import threading
from typing import Any, Optional


# ── internal store ──────────────────────────────────────────────────
# { key: (value, expire_timestamp) }
_store: dict[str, tuple[Any, float]] = {}
_lock = threading.Lock()

# How often the background reaper runs (seconds).
_REAP_INTERVAL = 60


# ── public API ──────────────────────────────────────────────────────

def get_cache(key: str) -> Optional[Any]:
    """Return the cached value if it exists and has not expired."""
    with _lock:
        entry = _store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.time() > expires_at:
            # Stale — remove and return miss
            del _store[key]
            return None
        return value


def set_cache(key: str, value: Any, ttl_seconds: int) -> None:
    """Store *value* under *key* with the given TTL (seconds)."""
    with _lock:
        _store[key] = (value, time.time() + ttl_seconds)


def invalidate_cache(key: str) -> None:
    """Remove a single key (no-op if not present)."""
    with _lock:
        _store.pop(key, None)


def clear_cache() -> None:
    """Wipe the entire cache — useful in tests or on deploy."""
    with _lock:
        _store.clear()


# ── background reaper ──────────────────────────────────────────────
# Lazily prunes expired entries so memory doesn't grow unbounded.

def _reap_expired() -> None:
    while True:
        time.sleep(_REAP_INTERVAL)
        now = time.time()
        with _lock:
            expired_keys = [
                k for k, (_, exp) in _store.items() if now > exp
            ]
            for k in expired_keys:
                del _store[k]


_reaper = threading.Thread(target=_reap_expired, daemon=True)
_reaper.start()
