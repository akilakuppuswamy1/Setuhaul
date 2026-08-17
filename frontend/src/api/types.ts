export interface Paginated<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

export interface HealthResponse {
  status: string;
  service: string;
}

export interface ConversationCreateRequest {
  driver_id: string;
  shipment_id?: string | null;
  subject?: string | null;
}

export interface ConversationCreateResponse {
  thread_id: string;
  driver_id: string | null;
  shipment_id: string | null;
  status: string;
}

export interface ToolCallRecord {
  name: string;
  success: boolean;
  error?: string | null;
}

export interface PresentedOption {
  index: number;
  slot_id: string;
  dock_id?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  label?: string | null;
}

export interface ConversationMetadata {
  intent?: string | null;
  requires_human?: boolean | null;
  tool_calls?: Array<{ name: string; success: boolean; error_code?: string | null }> | null;
  presented_options?: PresentedOption[] | null;
  selected_option_index?: number | null;
  latest_eta?: string | null;
  leave_by_local?: string | null;
  earliest_start_local?: string | null;
  escalation_reason?: string | null;
  exception_id?: string | null;
  proposal_slot_id?: string | null;
}

export interface ConversationMessageResponse {
  thread_id: string;
  message_id: string;
  response: string;
  intent: string;
  status: string;
  tool_calls: ToolCallRecord[];
  requires_clarification: boolean;
  requires_human: boolean;
  shipment_id: string | null;
  proposal_id: string | null;
  metadata?: ConversationMetadata | null;
}

export interface ChatThread {
  id: string;
  shipment_id: string | null;
  driver_id: string | null;
  driver_exception_id: string | null;
  subject: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  chat_thread_id: string;
  sender_type: string;
  content: string;
  sent_at: string;
  direction: "inbound" | "outbound";
  metadata?: Record<string, unknown> | null;
  created_at: string;
}

export interface Shipment {
  id: string;
  carrier_id: string;
  driver_id: string | null;
  vehicle_id: string | null;
  shipment_number: string;
  origin_location: string;
  destination_location: string;
  origin_facility_id: string | null;
  destination_facility_id: string | null;
  status: string;
  is_active: boolean;
  scheduled_pickup_at: string | null;
  scheduled_delivery_at: string | null;
  created_at: string;
  updated_at: string;
  latest_eta?: string | null;
}

export interface Driver {
  id: string;
  carrier_id: string;
  name: string;
  phone: string | null;
  external_id: string | null;
  status: string;
}

export interface Facility {
  id: string;
  name: string;
  code: string;
  address: string | null;
  timezone: string;
  status: string;
}

export interface Appointment {
  id: string;
  shipment_id: string;
  shipment_number?: string | null;
  facility_id: string;
  appointment_slot_id: string | null;
  dock_id: string | null;
  status: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface AppointmentSlot {
  id: string;
  facility_id: string;
  start_time: string;
  end_time: string;
  capacity: number;
  status: string;
}

export interface Dock {
  id: string;
  facility_id: string;
  name: string;
  dock_type: string;
  status: string;
}

export interface ETAUpdate {
  id: string;
  shipment_id: string;
  previous_eta: string | null;
  new_eta: string;
  update_timestamp: string;
  source: string;
  reason: string | null;
  created_at: string;
}

export interface LatestETA {
  shipment_id: string;
  latest_eta: string | null;
  eta_update: ETAUpdate | null;
}

export interface DriverException {
  id: string;
  shipment_id: string;
  driver_id: string | null;
  exception_type: string;
  description: string | null;
  status: string;
  occurred_at: string;
  resolved_at: string | null;
}

export interface Proposal {
  proposal_id: string;
  shipment_id: string;
  slot_id: string | null;
  dock_id: string | null;
  status: string;
  expires_at: string;
  message: string;
  reason: string | null;
  appointment_id: string | null;
}

export interface ScheduleAssignment {
  shipment_id: string;
  shipment_number: string;
  slot_id: string | null;
  dock_id: string | null;
  rank: number;
  score: number | null;
  kind: string;
  lateness_seconds: number | null;
  early_wait_seconds: number | null;
  alignment_seconds: number | null;
  yard_wait_seconds: number | null;
  reasons: string[];
}

export interface UnassignedShipment {
  shipment_id: string;
  shipment_number: string;
  reason: string;
  detail: string;
}

export interface ScheduleEvaluateResponse {
  facility_id: string;
  evaluated_at: string;
  scheduling_start: string;
  scheduling_end: string;
  ranking_policy: string;
  read_only: boolean;
  commits_capacity: boolean;
  candidate_shipments: Array<{
    shipment_id: string;
    shipment_number: string;
    status: string;
    latest_eta: string | null;
    gate_in_at: string | null;
    has_active_exception: boolean;
    missing_eta: boolean;
    protected: boolean;
  }>;
  proposed_assignments: ScheduleAssignment[];
  unassigned_shipments: UnassignedShipment[];
  warnings: string[];
}
