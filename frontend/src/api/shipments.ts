import { apiRequest } from "./client";
import type { Appointment, DriverException, ETAUpdate, LatestETA, Paginated, Shipment } from "./types";

export function listShipments(params: { driver_id?: string; facility_id?: string; status?: string } = {}) {
  const query = new URLSearchParams({ page: "1", page_size: "50" });
  if (params.driver_id) query.set("driver_id", params.driver_id);
  if (params.facility_id) query.set("facility_id", params.facility_id);
  if (params.status) query.set("status", params.status);
  return apiRequest<Paginated<Shipment>>(`/shipments?${query.toString()}`);
}

export function getShipment(shipmentId: string) {
  return apiRequest<Shipment>(`/shipments/${shipmentId}`);
}

export function getLatestEta(shipmentId: string) {
  return apiRequest<LatestETA>(`/shipments/${shipmentId}/latest-eta`);
}

export function listShipmentEtaUpdates(shipmentId: string) {
  return apiRequest<Paginated<ETAUpdate>>(`/shipments/${shipmentId}/eta-updates?page=1&page_size=50`);
}

export function listShipmentExceptions(shipmentId: string) {
  return apiRequest<Paginated<DriverException>>(`/shipments/${shipmentId}/exceptions?page=1&page_size=50`);
}

export function listShipmentAppointments(shipmentId: string) {
  return apiRequest<Paginated<Appointment>>(`/shipments/${shipmentId}/appointments?page=1&page_size=50`);
}
