import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ApiError } from "@/api/client";
import {
  acceptProposal,
  createConversation,
  getAppointmentSlot,
  getChatThread,
  getDock,
  getDriver,
  getFacility,
  getHealth,
  getLatestEta,
  getProposal,
  getShipment,
  listChatMessages,
  listFacilityDocks,
  listShipments,
  listShipmentAppointments,
  listShipmentEtaUpdates,
  listShipmentExceptions,
  rejectProposal,
  sendConversationMessage,
} from "@/api";
import type {
  Appointment,
  AppointmentSlot,
  ChatMessage,
  ConversationMessageResponse,
  Dock,
  Driver,
  DriverException,
  ETAUpdate,
  Facility,
  PresentedOption,
  Proposal,
  Shipment,
  ToolCallRecord,
} from "@/api/types";
import { loadingCopy } from "@/lib/format";

export interface ConsoleMessage {
  id: string;
  role: "driver" | "assistant";
  content: string;
  sentAt: string;
  intent?: string | null;
  toolCalls?: ToolCallRecord[];
  readOnlyStatus?: boolean;
  metadata?: ConversationMessageResponse["metadata"];
}

interface OpsState {
  healthOk: boolean | null;
  healthError: string | null;
  driver: Driver | null;
  shipment: Shipment | null;
  facility: Facility | null;
  appointments: Appointment[];
  etaHistory: ETAUpdate[];
  latestEta: string | null;
  exceptions: DriverException[];
  docks: Dock[];
  threadId: string | null;
  messages: ConsoleMessage[];
  options: PresentedOption[];
  selectedOptionIndex: number | null;
  proposal: Proposal | null;
  proposalSlot: AppointmentSlot | null;
  proposalDock: Dock | null;
  originalSlot: AppointmentSlot | null;
  conflict: ApiError | null;
  lastIntent: string | null;
  lastStatus: string | null;
  lastToolCalls: ToolCallRecord[];
  requiresHuman: boolean;
  escalationReason: string | null;
  composer: string;
  loading: boolean;
  loadingLabel: string | null;
  error: string | null;
  confirming: boolean;
  conversationReady: boolean;
}

interface OpsContextValue extends OpsState {
  timezone: string | undefined;
  originalAppointment: Appointment | undefined;
  setComposer: (value: string) => void;
  send: (text?: string) => Promise<void>;
  startConversation: () => Promise<void>;
  refreshOperational: () => Promise<void>;
  selectOption: (option: PresentedOption) => Promise<void>;
  confirmProposal: () => Promise<void>;
  rejectCurrentProposal: () => Promise<void>;
  findNewOptions: () => void;
}

const OpsContext = createContext<OpsContextValue | null>(null);

function metadataOptions(meta: ConversationMessageResponse["metadata"] | ChatMessage["metadata"]): PresentedOption[] {
  if (!meta || typeof meta !== "object") return [];
  const direct = (meta as { presented_options?: PresentedOption[] }).presented_options;
  if (Array.isArray(direct) && direct.length) return direct;
  const context = (meta as { context?: { presented_options?: PresentedOption[] } }).context;
  if (context && Array.isArray(context.presented_options)) return context.presented_options;
  return [];
}

function pickOriginalAppointment(appointments: Appointment[]): Appointment | undefined {
  const labeled = appointments.find((item) => (item.notes ?? "").includes("Original 6:30"));
  if (labeled) return labeled;
  return [...appointments].sort((a, b) => a.created_at.localeCompare(b.created_at))[0];
}

export function OpsProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<OpsState>({
    healthOk: null,
    healthError: null,
    driver: null,
    shipment: null,
    facility: null,
    appointments: [],
    etaHistory: [],
    latestEta: null,
    exceptions: [],
    docks: [],
    threadId: null,
    messages: [],
    options: [],
    selectedOptionIndex: null,
    proposal: null,
    proposalSlot: null,
    proposalDock: null,
    originalSlot: null,
    conflict: null,
    lastIntent: null,
    lastStatus: null,
    lastToolCalls: [],
    requiresHuman: false,
    escalationReason: null,
    composer: "",
    loading: false,
    loadingLabel: null,
    error: null,
    confirming: false,
    conversationReady: false,
  });

  const timezone = state.facility?.timezone;

  const applyTurn = useCallback(async (turn: ConversationMessageResponse, driverText: string) => {
    const options = metadataOptions(turn.metadata);
    let proposal: Proposal | null = null;
    if (turn.proposal_id) {
      try {
        proposal = await getProposal(turn.proposal_id);
      } catch {
        proposal = null;
      }
    }
    setState((prev) => ({
      ...prev,
      messages: [
        ...prev.messages,
        {
          id: `local-${Date.now()}`,
          role: "driver",
          content: driverText,
          sentAt: new Date().toISOString(),
        },
        {
          id: turn.message_id,
          role: "assistant",
          content: turn.response,
          sentAt: new Date().toISOString(),
          intent: turn.intent,
          toolCalls: turn.tool_calls,
          readOnlyStatus: turn.intent === "ASK_STATUS",
          metadata: turn.metadata,
        },
      ],
      options: options.length ? options : prev.options,
      selectedOptionIndex: turn.metadata?.selected_option_index ?? prev.selectedOptionIndex,
      proposal: proposal ?? prev.proposal,
      lastIntent: turn.intent,
      lastStatus: turn.status,
      lastToolCalls: turn.tool_calls,
      requiresHuman: turn.requires_human,
      escalationReason: turn.metadata?.escalation_reason ?? prev.escalationReason,
      conflict: turn.status === "stale" || turn.status === "conflict" ? new ApiError(409, turn.response, turn.status) : prev.conflict,
    }));
    if (turn.shipment_id && turn.shipment_id !== state.shipment?.id) {
      await loadShipment(turn.shipment_id);
    }
  }, [state.shipment?.id]);

  const loadShipment = useCallback(async (shipmentId: string) => {
    const [shipment, latest, etas, exceptions, appointments] = await Promise.all([
      getShipment(shipmentId),
      getLatestEta(shipmentId),
      listShipmentEtaUpdates(shipmentId),
      listShipmentExceptions(shipmentId),
      listShipmentAppointments(shipmentId),
    ]);
    const driver = shipment.driver_id ? await getDriver(shipment.driver_id) : null;
    const facility = shipment.destination_facility_id
      ? await getFacility(shipment.destination_facility_id)
      : null;
    const docks = shipment.destination_facility_id
      ? (await listFacilityDocks(shipment.destination_facility_id)).items
      : [];
    setState((prev) => ({
      ...prev,
      shipment,
      driver,
      facility,
      latestEta: latest.latest_eta,
      etaHistory: etas.items,
      exceptions: exceptions.items,
      appointments: appointments.items,
      docks,
    }));
  }, []);

  const bootstrap = useCallback(async () => {
    try {
      const health = await getHealth();
      const ok = health.status === "ok" && health.service === "setuhaul";
      setState((prev) => ({
        ...prev,
        healthOk: ok,
        healthError: ok
          ? null
          : "Connected host is not the SetuHaul API. Set VITE_API_BASE_URL to the uvicorn process running app.main:app.",
      }));
      if (!ok) return;
    } catch (error) {
      setState((prev) => ({
        ...prev,
        healthOk: false,
        healthError: error instanceof ApiError ? error.message : "API unreachable",
      }));
      return;
    }
    try {
      const listed = await listShipments();
      const preferred =
        listed.items.find((item) => item.shipment_number === "SH-1024") ??
        listed.items.find((item) => item.driver_id && item.is_active) ??
        listed.items[0];
      if (!preferred) {
        setState((prev) => ({
          ...prev,
          error: "No shipments found. Seed the demo dataset, then refresh.",
        }));
        return;
      }
      await loadShipment(preferred.id);
    } catch (error) {
      setState((prev) => ({
        ...prev,
        error: error instanceof ApiError ? error.message : "Unable to load shipments.",
      }));
    }
  }, [loadShipment]);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  const refreshOperational = useCallback(async () => {
    if (!state.shipment) return;
    await loadShipment(state.shipment.id);
    if (state.proposal?.proposal_id) {
      try {
        const proposal = await getProposal(state.proposal.proposal_id);
        setState((prev) => ({ ...prev, proposal }));
      } catch {
        /* proposal may have been superseded */
      }
    }
  }, [loadShipment, state.proposal?.proposal_id, state.shipment]);

  const startConversation = useCallback(async () => {
    if (!state.driver || !state.shipment) return;
    setState((prev) => ({ ...prev, loading: true, loadingLabel: "Opening conversation…", error: null }));
    try {
      const created = await createConversation({
        driver_id: state.driver.id,
        shipment_id: state.shipment.id,
        subject: `Driver console · ${state.shipment.shipment_number}`,
      });
      setState((prev) => ({
        ...prev,
        threadId: created.thread_id,
        messages: [],
        options: [],
        proposal: null,
        conflict: null,
        lastIntent: null,
        lastStatus: created.status,
        conversationReady: true,
      }));
    } catch (error) {
      setState((prev) => ({
        ...prev,
        conversationReady: true,
        error: error instanceof ApiError ? error.message : "Could not create conversation.",
      }));
    } finally {
      setState((prev) => ({ ...prev, loading: false, loadingLabel: null }));
    }
  }, [state.driver, state.shipment]);

  useEffect(() => {
    if (state.driver && state.shipment && !state.threadId && !state.loading && !state.conversationReady) {
      void startConversation();
    }
  }, [state.driver, state.shipment, state.threadId, state.loading, state.conversationReady, startConversation]);

  const hydrateThread = useCallback(async (threadId: string) => {
    const [thread, page] = await Promise.all([getChatThread(threadId), listChatMessages(threadId)]);
    const mapped: ConsoleMessage[] = page.items.map((item) => ({
      id: item.id,
      role: item.direction === "inbound" ? "driver" : "assistant",
      content: item.content,
      sentAt: item.sent_at,
      metadata: item.metadata as ConversationMessageResponse["metadata"],
    }));
    let options: PresentedOption[] = [];
    for (const item of page.items) {
      const found = metadataOptions(item.metadata);
      if (found.length) options = found;
    }
    setState((prev) => ({
      ...prev,
      threadId: thread.id,
      messages: mapped,
      options: options.length ? options : prev.options,
      conversationReady: true,
    }));
  }, []);

  useEffect(() => {
    if (state.threadId && !state.conversationReady) {
      void hydrateThread(state.threadId).catch(() => undefined);
    }
  }, [hydrateThread, state.conversationReady, state.threadId]);

  useEffect(() => {
    let cancelled = false;
    async function loadProposalDetails() {
      if (!state.proposal) return;
      const slot = state.proposal.slot_id ? await getAppointmentSlot(state.proposal.slot_id) : null;
      const dock = state.proposal.dock_id ? await getDock(state.proposal.dock_id) : null;
      if (!cancelled) {
        setState((prev) => ({ ...prev, proposalSlot: slot, proposalDock: dock }));
      }
    }
    void loadProposalDetails();
    return () => {
      cancelled = true;
    };
  }, [state.proposal]);

  useEffect(() => {
    let cancelled = false;
    async function loadOriginalSlot() {
      const appointment = pickOriginalAppointment(state.appointments);
      if (!appointment?.appointment_slot_id) {
        if (!cancelled) setState((prev) => ({ ...prev, originalSlot: null }));
        return;
      }
      const slot = await getAppointmentSlot(appointment.appointment_slot_id);
      if (!cancelled) setState((prev) => ({ ...prev, originalSlot: slot }));
    }
    void loadOriginalSlot();
    return () => {
      cancelled = true;
    };
  }, [state.appointments]);

  const send = useCallback(
    async (text?: string) => {
      const message = (text ?? state.composer).trim();
      if (!message || !state.threadId) return;
      const kind = /confirm it|book it|lock it in/i.test(message) ? "confirm" : "message";
      setState((prev) => ({
        ...prev,
        loading: true,
        loadingLabel: loadingCopy(message),
        composer: "",
        error: null,
        conflict: null,
        confirming: kind === "confirm",
      }));
      try {
        const turn = await sendConversationMessage(state.threadId, message);
        await applyTurn(turn, message);
        await refreshOperational();
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          setState((prev) => ({ ...prev, conflict: error }));
        } else {
          setState((prev) => ({
            ...prev,
            error: error instanceof ApiError ? error.message : "Message could not be sent.",
          }));
        }
      } finally {
        setState((prev) => ({ ...prev, loading: false, loadingLabel: null, confirming: false }));
      }
    },
    [applyTurn, refreshOperational, state.composer, state.threadId],
  );

  const selectOption = useCallback(
    async (option: PresentedOption) => {
      setState((prev) => ({ ...prev, selectedOptionIndex: option.index }));
      await send(`Option ${option.index}`);
    },
    [send],
  );

  const confirmProposal = useCallback(async () => {
    if (state.threadId) {
      await send("Confirm it.");
      return;
    }
    if (!state.proposal) return;
    setState((prev) => ({ ...prev, loading: true, loadingLabel: "Revalidating…", confirming: true }));
    try {
      const proposal = await acceptProposal(state.proposal.proposal_id);
      setState((prev) => ({ ...prev, proposal, conflict: null }));
      await refreshOperational();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setState((prev) => ({ ...prev, conflict: error }));
      } else {
        setState((prev) => ({
          ...prev,
          error: error instanceof ApiError ? error.message : "Confirmation failed.",
        }));
      }
    } finally {
      setState((prev) => ({ ...prev, loading: false, loadingLabel: null, confirming: false }));
    }
  }, [refreshOperational, send, state.proposal, state.threadId]);

  const rejectCurrentProposal = useCallback(async () => {
    if (state.threadId) {
      await send("reject");
      return;
    }
    if (!state.proposal) return;
    const proposal = await rejectProposal(state.proposal.proposal_id);
    setState((prev) => ({ ...prev, proposal }));
  }, [send, state.proposal, state.threadId]);

  const originalAppointment = useMemo(() => pickOriginalAppointment(state.appointments), [state.appointments]);

  const value: OpsContextValue = {
    ...state,
    timezone,
    originalAppointment,
    setComposer: (composer) => setState((prev) => ({ ...prev, composer })),
    send,
    startConversation,
    refreshOperational,
    selectOption,
    confirmProposal,
    rejectCurrentProposal,
    findNewOptions: () => setState((prev) => ({ ...prev, composer: "What options do I have?", conflict: null })),
  };

  return <OpsContext.Provider value={value}>{children}</OpsContext.Provider>;
}

export function useOps() {
  const value = useContext(OpsContext);
  if (!value) throw new Error("useOps must be used within OpsProvider");
  return value;
}
