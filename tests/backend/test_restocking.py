"""
Tests for restocking API endpoints.
"""
from datetime import date, timedelta

import pytest


class TestRestockingEndpoints:
    """Test suite for restocking order endpoints."""

    def _forecasts(self, client):
        return {f["item_sku"]: f for f in client.get("/api/demand").json()}

    def test_demand_includes_restocking_fields(self, client):
        """Demand forecasts expose cost, stock and lead time."""
        response = client.get("/api/demand")
        assert response.status_code == 200

        for forecast in response.json():
            assert forecast["unit_cost"] > 0
            assert forecast["current_stock"] >= 0
            assert forecast["lead_time_days"] > 0

    def test_create_restocking_order(self, client):
        """Test submitting an order computes total, lead time and delivery date."""
        forecasts = self._forecasts(client)
        skus = list(forecasts)[:2]
        payload = {"items": [{"sku": skus[0], "quantity": 10}, {"sku": skus[1], "quantity": 5}]}

        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        expected_total = round(
            10 * forecasts[skus[0]]["unit_cost"] + 5 * forecasts[skus[1]]["unit_cost"], 2
        )
        expected_lead = max(forecasts[s]["lead_time_days"] for s in skus)

        assert order["status"] == "Submitted"
        assert order["order_number"].startswith("RST-")
        assert order["total_cost"] == expected_total
        assert order["lead_time_days"] == expected_lead
        assert order["order_date"] == date.today().isoformat()
        assert order["expected_delivery"] == (date.today() + timedelta(days=expected_lead)).isoformat()
        assert [i["sku"] for i in order["items"]] == skus

    def test_client_cannot_set_price(self, client):
        """Prices come from the forecast, not the request."""
        forecasts = self._forecasts(client)
        sku = next(iter(forecasts))
        payload = {"items": [{"sku": sku, "quantity": 1, "unit_cost": 0.01}]}

        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 201
        assert response.json()["items"][0]["unit_cost"] == forecasts[sku]["unit_cost"]

    def test_create_order_empty_items(self, client):
        """Test an empty order is rejected."""
        response = client.post("/api/restocking-orders", json={"items": []})
        assert response.status_code == 400

    @pytest.mark.parametrize("quantity", [0, -5])
    def test_create_order_invalid_quantity(self, client, quantity):
        """Test non-positive quantities are rejected."""
        sku = next(iter(self._forecasts(client)))
        response = client.post(
            "/api/restocking-orders", json={"items": [{"sku": sku, "quantity": quantity}]}
        )
        assert response.status_code == 400

    def test_create_order_unknown_sku(self, client):
        """Test an unknown SKU is rejected."""
        response = client.post(
            "/api/restocking-orders", json={"items": [{"sku": "NOPE-000", "quantity": 1}]}
        )
        assert response.status_code == 400
        assert "NOPE-000" in response.json()["detail"]

    def test_create_order_missing_body_fields(self, client):
        """Test a malformed body fails validation."""
        response = client.post("/api/restocking-orders", json={"items": [{"sku": "WDG-001"}]})
        assert response.status_code == 422

    def test_get_restocking_orders_newest_first(self, client):
        """Test submitted orders are listed newest first."""
        sku = next(iter(self._forecasts(client)))
        first = client.post("/api/restocking-orders", json={"items": [{"sku": sku, "quantity": 1}]}).json()
        second = client.post("/api/restocking-orders", json={"items": [{"sku": sku, "quantity": 2}]}).json()

        response = client.get("/api/restocking-orders")
        assert response.status_code == 200

        ids = [o["id"] for o in response.json()]
        assert ids.index(second["id"]) < ids.index(first["id"])
