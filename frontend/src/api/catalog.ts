import { apiRequest } from "./client";
import type { Appointment, AppointmentSlot, Dock, Driver, Facility, HealthResponse, Paginated } from "./types";

export function getHealth() {
  return apiRequest<HealthResponse>("/health");
}

export function listDrivers() {
  return apiRequest<Paginated<Driver>>("/drivers?page=1&page_size=50");
}

export function getDriver(driverId: string) {
  return apiRequest<Driver>(`/drivers/${driverId}`);
}

export function listFacilities() {
  return apiRequest<Paginated<Facility>>("/facilities?page=1&page_size=50");
}

export function getFacility(facilityId: string) {
  return apiRequest<Facility>(`/facilities/${facilityId}`);
}

export function getDock(dockId: string) {
  return apiRequest<Dock>(`/docks/${dockId}`);
}

export function getAppointmentSlot(slotId: string) {
  return apiRequest<AppointmentSlot>(`/appointment-slots/${slotId}`);
}

export function listAppointments(params: { facility_id?: string; shipment_id?: string; appointment_status?: string } = {}) {
  const query = new URLSearchParams({ page: "1", page_size: "50" });
  if (params.facility_id) query.set("facility_id", params.facility_id);
  if (params.shipment_id) query.set("shipment_id", params.shipment_id);
  if (params.appointment_status) query.set("appointment_status", params.appointment_status);
  return apiRequest<Paginated<Appointment>>(`/appointments?${query.toString()}`);
}

export function listFacilityDocks(facilityId: string) {
  return apiRequest<Paginated<Dock>>(`/facilities/${facilityId}/docks?page=1&page_size=50`);
}
