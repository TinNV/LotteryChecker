from lottery_checker.analytics import TrafficTracker


def test_tracker_ignores_static_requests() -> None:
    now_ref = [1_700_000_000.0]
    tracker = TrafficTracker(now_fn=lambda: now_ref[0])

    tracker.record(
        method="GET",
        path="/static/style.css",
        status_code=200,
        ip="127.0.0.1",
        duration_ms=4,
        accept="text/css,*/*",
        user_agent="pytest",
    )

    snapshot = tracker.snapshot(series_minutes=5)
    assert snapshot["total_requests"] == 0
    assert snapshot["top_paths"] == []


def test_tracker_ignores_admin_and_health_paths() -> None:
    now_ref = [1_700_000_000.0]
    tracker = TrafficTracker(now_fn=lambda: now_ref[0])

    tracker.record(
        method="GET",
        path="/admin",
        status_code=200,
        ip="127.0.0.1",
        duration_ms=6,
        accept="text/html",
        user_agent="pytest",
    )
    tracker.record(
        method="GET",
        path="/health",
        status_code=200,
        ip="127.0.0.1",
        duration_ms=2,
        accept="application/json",
        user_agent="pytest",
    )

    snapshot = tracker.snapshot(series_minutes=5)
    assert snapshot["total_requests"] == 0
    assert snapshot["top_paths"] == []


def test_tracker_dedupes_refresh_page_views() -> None:
    now_ref = [1_700_000_000.0]
    tracker = TrafficTracker(refresh_window_seconds=15, now_fn=lambda: now_ref[0])

    kwargs = {
        "method": "GET",
        "path": "/",
        "status_code": 200,
        "ip": "203.0.113.10",
        "duration_ms": 12,
        "accept": "text/html,application/xhtml+xml",
        "user_agent": "pytest-browser",
    }

    tracker.record(**kwargs)
    now_ref[0] += 5
    tracker.record(**kwargs)  # refresh within dedupe window -> ignore
    now_ref[0] += 20
    tracker.record(**kwargs)

    snapshot = tracker.snapshot(series_minutes=5)
    assert snapshot["total_requests"] == 2
    assert snapshot["top_paths"][0][0] == "/"
    assert snapshot["top_paths"][0][1] == 2


def test_tracker_keeps_post_search_requests() -> None:
    now_ref = [1_700_000_000.0]
    tracker = TrafficTracker(refresh_window_seconds=15, now_fn=lambda: now_ref[0])

    payload = {
        "method": "POST",
        "path": "/",
        "status_code": 200,
        "ip": "198.51.100.8",
        "duration_ms": 28,
        "accept": "text/html,application/xhtml+xml",
        "user_agent": "pytest-browser",
    }

    tracker.record(**payload)
    now_ref[0] += 2
    tracker.record(**payload)

    snapshot = tracker.snapshot(series_minutes=5)
    assert snapshot["total_requests"] == 2
    assert snapshot["status_counts"] == [(200, 2)]


def test_tracker_builds_minute_series() -> None:
    now_ref = [1_700_000_000.0]
    tracker = TrafficTracker(now_fn=lambda: now_ref[0])

    tracker.record(
        method="POST",
        path="/",
        status_code=200,
        ip="198.51.100.8",
        duration_ms=20,
        accept="text/html",
        user_agent="pytest",
    )
    now_ref[0] += 60
    tracker.record(
        method="POST",
        path="/",
        status_code=200,
        ip="198.51.100.8",
        duration_ms=24,
        accept="text/html",
        user_agent="pytest",
    )

    snapshot = tracker.snapshot(series_minutes=3)
    assert len(snapshot["minute_series"]) == 3
    assert snapshot["minute_series"][-1]["count"] == 1
