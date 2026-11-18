"""Calibración del modelo de rutas con distancias y tiempos medidos."""

from __future__ import annotations

from tests.conftest import create_structure


def _location(admin_client, warehouse_id, aisle, position, level="N01"):
    response = admin_client.post(
        "/api/v1/locations",
        json={
            "warehouse_id": warehouse_id,
            "aisle": aisle,
            "rack": "EA",
            "level": level,
            "position": position,
            "capacity_pallets": 2,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_default_manual_and_route_impact(admin_client, worker_client):
    structure = create_structure(admin_client)
    current = admin_client.get("/api/v1/optimization/calibration")
    assert current.status_code == 200, current.text
    data = current.json()
    assert data["is_default"] is True
    assert data["method"] == "default"
    assert data["assumptions"]["aisle_pitch_m"] == 3.0
    assert data["assumptions"]["walking_speed_mps"] == 1.0

    assert worker_client.put(
        "/api/v1/optimization/calibration", json={}
    ).status_code == 403

    updated = admin_client.put(
        "/api/v1/optimization/calibration",
        json={
            "warehouse_id": structure["warehouse_id"],
            "aisle_pitch_m": "4.5",
            "rack_pitch_m": "7.0",
            "position_pitch_m": "1.2",
            "base_pick_seconds": "30",
            "level_penalty_seconds": "8",
            "walking_speed_mps": "1.25",
            "setup_seconds": "20",
            "notes": "Plano medido con cinta métrica",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["method"] == "manual"
    assert updated.json()["is_default"] is False
    assert updated.json()["assumptions"]["walking_speed_mps"] == 1.25
    assert updated.json()["calibrated_by"] == "Admin Prueba"

    second = _location(admin_client, structure["warehouse_id"], "P06", "POS01")
    route = admin_client.post(
        "/api/v1/optimization/picking-route",
        json={"location_ids": [structure["location_id"], second["id"]]},
    )
    assert route.status_code == 200, route.text
    payload = route.json()
    assert payload["calibration"]["method"] == "manual"
    assert payload["assumptions"]["aisle_pitch_m"] == 4.5
    assert payload["total_walk_seconds"] > 0
    assert payload["total_estimated_seconds"] == (
        payload["setup_seconds"] + payload["total_walk_seconds"] + payload["total_pick_seconds"]
    )


def test_time_samples_and_regression_fit(admin_client):
    structure = create_structure(admin_client)
    locations = [
        _location(admin_client, structure["warehouse_id"], "P01", "POS01"),
        _location(admin_client, structure["warehouse_id"], "P02", "POS02"),
        _location(admin_client, structure["warehouse_id"], "P08", "POS04", level="N03"),
    ]

    insufficient = admin_client.post("/api/v1/optimization/calibration/fit")
    assert insufficient.status_code == 422
    assert insufficient.json()["error"]["code"] == "insufficient_samples"

    sets = [
        [structure["location_id"]],
        [structure["location_id"], locations[0]["id"]],
        [structure["location_id"], locations[1]["id"], locations[2]["id"]],
    ]
    for index, location_ids in enumerate(sets):
        sample = admin_client.post(
            "/api/v1/optimization/time-studies",
            json={
                "location_ids": location_ids,
                "measured_seconds": 45 + index * 35,
                "notes": f"Cronometraje {index + 1}",
            },
        )
        assert sample.status_code == 201, sample.text
        assert sample.json()["stops"] == len(location_ids)
        assert float(sample.json()["distance_m"]) > 0
        assert sample.json()["measurer_name"] == "Admin Prueba"

    fitted = admin_client.post("/api/v1/optimization/calibration/fit")
    assert fitted.status_code == 200, fitted.text
    result = fitted.json()
    assert result["method"] == "regression"
    assert result["total_samples"] == 3
    assert result["fit"]["sample_count"] == 3
    assert 0.2 <= result["parameters"]["walking_speed_mps"] <= 3.0
    assert result["r_squared"] is not None
    assert len(result["samples"]) == 3

    refreshed = admin_client.get("/api/v1/optimization/calibration").json()
    assert refreshed["method"] == "regression"
    assert refreshed["calibrated_at"] is not None

    sample_id = refreshed["samples"][0]["id"]
    assert admin_client.delete(f"/api/v1/optimization/time-studies/{sample_id}").status_code == 204
    assert admin_client.get("/api/v1/optimization/calibration").json()["total_samples"] == 2

    assert admin_client.post(
        "/api/v1/optimization/time-studies",
        json={"location_ids": ["no-existe"], "measured_seconds": 30},
    ).status_code == 404
