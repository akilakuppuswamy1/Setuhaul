"""Step 3 business API tests."""

import uuid

import pytest
from fastapi.testclient import TestClient


class TestHealthAndOpenAPI:
    def test_health(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "setuhaul"}

    def test_openapi_json(self, client: TestClient) -> None:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert schema["info"]["title"] == "SetuHaul"
        assert "/shipments" in schema["paths"]


class TestCarrierAPI:
    def test_list_empty(self, client: TestClient) -> None:
        response = client.get("/carriers")
        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["page"] == 1

    def test_get_by_id(self, seeded_client: TestClient, seeded_session: dict) -> None:
        carrier = seeded_session["carrier"]
        response = seeded_client.get(f"/carriers/{carrier.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(carrier.id)
        assert data["code"] == "ACME"
        assert data["name"] == "Acme Logistics"

    def test_get_not_found(self, seeded_client: TestClient) -> None:
        response = seeded_client.get(f"/carriers/{uuid.uuid4()}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_list_with_data(self, seeded_client: TestClient) -> None:
        response = seeded_client.get("/carriers")
        assert response.status_code == 200
        assert response.json()["total"] == 1


class TestDriverAPI:
    def test_list_filter_by_carrier(self, seeded_client: TestClient, seeded_session: dict) -> None:
        carrier = seeded_session["carrier"]
        response = seeded_client.get("/drivers", params={"carrier_id": str(carrier.id)})
        assert response.status_code == 200
        assert response.json()["total"] == 2

    def test_get_driver(self, seeded_client: TestClient, seeded_session: dict) -> None:
        driver = seeded_session["drivers"][0]
        response = seeded_client.get(f"/drivers/{driver.id}")
        assert response.status_code == 200
        assert response.json()["name"] == "Jane Rivera"


class TestVehicleAPI:
    def test_list_vehicles(self, seeded_client: TestClient) -> None:
        response = seeded_client.get("/vehicles")
        assert response.status_code == 200
        assert response.json()["total"] == 2


class TestShipmentAPI:
    def test_list_filter_by_status(self, seeded_client: TestClient) -> None:
        response = seeded_client.get("/shipments", params={"status": "in_transit"})
        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_list_filter_by_is_active(self, seeded_client: TestClient) -> None:
        response = seeded_client.get("/shipments", params={"is_active": False})
        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_get_shipment_with_latest_eta(
        self, seeded_client: TestClient, seeded_session: dict
    ) -> None:
        shipment = seeded_session["shipments"][0]
        response = seeded_client.get(f"/shipments/{shipment.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["shipment_number"] == "SHP-1001"
        assert data["latest_eta"] is not None

    def test_shipment_eta_history(self, seeded_client: TestClient, seeded_session: dict) -> None:
        shipment = seeded_session["shipments"][0]
        response = seeded_client.get(f"/shipments/{shipment.id}/eta-updates")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2

    def test_shipment_exceptions(self, seeded_client: TestClient, seeded_session: dict) -> None:
        shipment = seeded_session["shipments"][0]
        response = seeded_client.get(f"/shipments/{shipment.id}/exceptions")
        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_shipment_appointments(self, seeded_client: TestClient, seeded_session: dict) -> None:
        shipment = seeded_session["shipments"][0]
        response = seeded_client.get(f"/shipments/{shipment.id}/appointments")
        assert response.status_code == 200
        assert response.json()["total"] == 2

    def test_shipment_checkins(self, seeded_client: TestClient, seeded_session: dict) -> None:
        shipment = seeded_session["shipments"][0]
        response = seeded_client.get(f"/shipments/{shipment.id}/facility-checkins")
        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_shipment_chat_threads(self, seeded_client: TestClient, seeded_session: dict) -> None:
        shipment = seeded_session["shipments"][0]
        response = seeded_client.get(f"/shipments/{shipment.id}/chat-threads")
        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_shipment_not_found(self, seeded_client: TestClient) -> None:
        response = seeded_client.get(f"/shipments/{uuid.uuid4()}/eta-updates")
        assert response.status_code == 404


class TestFacilityAPI:
    def test_get_facility(self, seeded_client: TestClient, seeded_session: dict) -> None:
        facility = seeded_session["facility"]
        response = seeded_client.get(f"/facilities/{facility.id}")
        assert response.status_code == 200
        assert response.json()["code"] == "CRDC-01"

    def test_facility_docks(self, seeded_client: TestClient, seeded_session: dict) -> None:
        facility = seeded_session["facility"]
        response = seeded_client.get(f"/facilities/{facility.id}/docks")
        assert response.status_code == 200
        assert response.json()["total"] == 2

    def test_facility_rules(self, seeded_client: TestClient, seeded_session: dict) -> None:
        facility = seeded_session["facility"]
        response = seeded_client.get(f"/facilities/{facility.id}/rules")
        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_facility_appointment_slots(
        self, seeded_client: TestClient, seeded_session: dict
    ) -> None:
        facility = seeded_session["facility"]
        response = seeded_client.get(f"/facilities/{facility.id}/appointment-slots")
        assert response.status_code == 200
        assert response.json()["total"] == 2

    def test_facility_checkins(self, seeded_client: TestClient, seeded_session: dict) -> None:
        facility = seeded_session["facility"]
        response = seeded_client.get(f"/facilities/{facility.id}/check-ins")
        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_facility_name_filter(self, seeded_client: TestClient) -> None:
        response = seeded_client.get("/facilities", params={"facility_name": "Central"})
        assert response.status_code == 200
        assert response.json()["total"] == 1


class TestAppointmentAPI:
    def test_list_appointments(self, seeded_client: TestClient) -> None:
        response = seeded_client.get("/appointments")
        assert response.status_code == 200
        assert response.json()["total"] == 2

    def test_filter_by_status(self, seeded_client: TestClient) -> None:
        response = seeded_client.get("/appointments", params={"appointment_status": "confirmed"})
        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_get_appointment(self, seeded_client: TestClient, seeded_session: dict) -> None:
        appointment = seeded_session["appointments"][0]
        response = seeded_client.get(f"/appointments/{appointment.id}")
        assert response.status_code == 200
        assert response.json()["status"] == "confirmed"


class TestOperationsAPI:
    def test_eta_updates_list(self, seeded_client: TestClient) -> None:
        response = seeded_client.get("/eta-updates")
        assert response.status_code == 200
        assert response.json()["total"] == 2

    def test_driver_exceptions_list(self, seeded_client: TestClient) -> None:
        response = seeded_client.get("/driver-exceptions")
        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_facility_checkins_list(self, seeded_client: TestClient) -> None:
        response = seeded_client.get("/facility-checkins")
        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_operational_messages_list(self, seeded_client: TestClient) -> None:
        response = seeded_client.get("/operational-messages")
        assert response.status_code == 200
        assert response.json()["total"] == 1


class TestConversationsAPI:
    def test_chat_threads(self, seeded_client: TestClient) -> None:
        response = seeded_client.get("/chat-threads")
        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_chat_messages(self, seeded_client: TestClient, seeded_session: dict) -> None:
        thread = seeded_session["thread"]
        response = seeded_client.get("/chat-messages", params={"chat_thread_id": str(thread.id)})
        assert response.status_code == 200
        assert response.json()["total"] == 2

    def test_contacts(self, seeded_client: TestClient) -> None:
        response = seeded_client.get("/contacts")
        assert response.status_code == 200
        assert response.json()["total"] == 1


class TestPaginationAndValidation:
    def test_pagination(self, seeded_client: TestClient) -> None:
        response = seeded_client.get("/shipments", params={"page": 1, "page_size": 2})
        assert response.status_code == 200
        body = response.json()
        assert body["page"] == 1
        assert body["page_size"] == 2
        assert len(body["items"]) == 2
        assert body["total"] == 3

    def test_invalid_uuid(self, seeded_client: TestClient) -> None:
        response = seeded_client.get("/carriers/not-a-uuid")
        assert response.status_code == 422

    def test_invalid_page_size(self, seeded_client: TestClient) -> None:
        response = seeded_client.get("/carriers", params={"page_size": 0})
        assert response.status_code == 422

    def test_page_size_max(self, seeded_client: TestClient) -> None:
        response = seeded_client.get("/carriers", params={"page_size": 101})
        assert response.status_code == 422
