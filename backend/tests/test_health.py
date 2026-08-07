def test_live_health(client):
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_capabilities_exposes_framework_stage(client):
    response = client.get("/api/v1/meta/capabilities")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["project"] == "ESR-Platform-Next"
    assert payload["stage"] == "framework"
    assert payload["coordinate_system"] == "EPSG:4326"
