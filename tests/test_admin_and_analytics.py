import base64
from types import SimpleNamespace

import app as app_module


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def test_admin_uses_local_default_credentials(monkeypatch) -> None:
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    with app_module.app.test_client() as client:
        response = client.get("/admin")
    assert response.status_code == 401

    headers = _basic_auth("admin", "admin_P@ssw0rd")
    with app_module.app.test_client() as client:
        response = client.get("/admin", headers=headers)
    assert response.status_code == 200


def test_admin_requires_basic_auth(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    with app_module.app.test_client() as client:
        response = client.get("/admin")
    assert response.status_code == 401


def test_admin_accepts_correct_credentials(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    headers = _basic_auth("admin", "secret")
    with app_module.app.test_client() as client:
        response = client.get("/admin", headers=headers)
    assert response.status_code == 200
    assert b"Admin Dashboard" in response.data


def test_persist_history_handles_store_errors(monkeypatch) -> None:
    class FailingStore:
        def save_search(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    monkeypatch.setattr(app_module, "search_store", FailingStore())
    history_entry = {
        "mode": "number",
        "game": "number:loto6",
        "draw_number": "100",
        "summary": "1/1",
        "tickets": [{"raw": "1 2 3 4 5 6"}],
    }

    with app_module.app.test_request_context("/", headers={"User-Agent": "pytest-agent"}):
        app_module._persist_search_history(
            history_entry=history_entry,
            number_ticket_results=[{"winning": True}],
            traditional_ticket_results=[],
        )


def test_persist_history_sends_expected_payload(monkeypatch) -> None:
    class CaptureStore:
        def __init__(self) -> None:
            self.payload = None

        def save_search(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.payload = kwargs

    capture = CaptureStore()
    monkeypatch.setattr(app_module, "search_store", capture)

    history_entry = {
        "mode": "traditional",
        "game": "traditional:zenkoku",
        "draw_number": "200",
        "summary": "2/3",
        "tickets": [
            {"group": "12", "number": "123456"},
            {"group": "15", "number": "456789"},
            {"group": "20", "number": "000001"},
        ],
    }

    with app_module.app.test_request_context(
        "/",
        headers={"User-Agent": "pytest-agent", "X-Forwarded-For": "203.0.113.10"},
    ):
        app_module._persist_search_history(
            history_entry=history_entry,
            number_ticket_results=[],
            traditional_ticket_results=[{"winning": True}, {"winning": False}, {"winning": True}],
        )

    assert capture.payload is not None
    assert capture.payload["mode"] == "traditional"
    assert capture.payload["ticket_count"] == 3
    assert capture.payload["winning_count"] == 2
    assert capture.payload["client_ip"] == "203.0.113.10"


def test_build_history_entry_number_summary_has_ticket_and_money() -> None:
    history = app_module._build_history_entry(
        mode="number",
        selected_game="number:loto6",
        number_draw_result=SimpleNamespace(draw_number=123),
        traditional_draw_result=None,
        number_ticket_rows=["1 2 3 4 5 6", "1 2 3 4 5 7"],
        traditional_ticket_rows=[],
        number_ticket_results=[
            {"winning": True, "payout": "1,000円"},
            {"winning": False, "payout": "-"},
        ],
        traditional_ticket_results=[],
    )

    assert history is not None
    assert history["summary"] == "2 vé | 1 trúng | Thưởng: 1,000円"


def test_build_history_entry_traditional_summary_has_ticket_and_money() -> None:
    history = app_module._build_history_entry(
        mode="traditional",
        selected_game="traditional:zenkoku",
        number_draw_result=None,
        traditional_draw_result=SimpleNamespace(draw_order=456),
        number_ticket_rows=[],
        traditional_ticket_rows=[
            {"group": "12", "number": "123456"},
            {"group": "13", "number": "654321"},
        ],
        number_ticket_results=[],
        traditional_ticket_results=[
            {"winning": True, "payout_yen": 3000},
            {"winning": False, "payout_yen": 0},
        ],
    )

    assert history is not None
    assert history["summary"] == "2 vé | 1 trúng | Thưởng: 3,000円"
