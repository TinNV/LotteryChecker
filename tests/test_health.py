from app import app


def test_health_endpoint_returns_ok() -> None:
    with app.test_client() as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
