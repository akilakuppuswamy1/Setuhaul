import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
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
import {
  hasSupersededHistory,
  pickCurrentAppointment,
  pickOriginalAppointment,
  pickPendingProposalAppointment,
  pickStaleProposalAppointment,
} from "@/lib/appointments";
import {
  BOOTSTRAP_TIMEOUT_MS,
  isRetryableBootstrapError,
  retryBootstrap,
} from "@/lib/bootstrapRetry";
import { isConversationThreadMissing, sendDriverMessage } from "@/lib/conversationThread";
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
  shipments: Shipment[];
  threadId: string | null;
  messages: ConsoleMessage[];
  options: PresentedOption[];
  selectedOptionIndex: number | null;
  proposal: Proposal | null;
  proposalSlot: AppointmentSlot | null;
  proposalDock: Dock | null;
  originalSlot: AppointmentSlot | null;
  currentSlot: AppointmentSlot | null;
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
  connecting: boolean;
  connectionError: boolean;
  confirming: boolean;
  conversationReady: boolean;
}

interface OpsContextValue extends OpsState {
  timezone: string | undefined;
  originalAppointment: Appointment | undefined;
  currentAppointment: Appointment | undefined;
  rescheduled: boolean;
  setComposer: (value: string) => void;
  send: (text?: string) => Promise<void>;
  startConversation: () => Promise<void>;
  refreshOperational: () => Promise<void>;
  selectShipment: (shipmentId: string) => Promise<void>;
  selectOption: (option: PresentedOption) => Promise<void>;
  confirmProposal: () => Promise<void>;
  rejectCurrentProposal: () => Promise<void>;
  findNewOptions: () => void;
  retryBootstrap: () => Promise<void>;
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
    shipments: [],
    threadId: null,
    messages: [],
    options: [],
    selectedOptionIndex: null,
    proposal: null,
    proposalSlot: null,
    proposalDock: null,
    originalSlot: null,
    currentSlot: null,
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
    connecting: true,
    connectionError: false,
    confirming: false,
    conversationReady: false,
  });
  const boundShipmentId = useRef<string | null>(null);
  const bootstrapGeneration = useRef(0);

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
    const acceptFailed = (turn.tool_calls ?? []).some(
      (call) => call.name === "accept_proposal" && call.success === false,
    );
    const staleTurn = turn.status === "stale" || turn.status === "conflict" || acceptFailed;
    if (staleTurn && proposal?.status === "confirmed") {
      proposal = null;
    }
    const proposalConfirmed =
      proposal?.status === "confirmed" ||
      (turn.status === "ok" && turn.intent === "ACCEPT_PROPOSAL" && !acceptFailed);
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
      options: proposalConfirmed ? [] : options.length ? options : prev.options,
      selectedOptionIndex: proposalConfirmed
        ? null
        : (turn.metadata?.selected_option_index ?? prev.selectedOptionIndex),
      proposal: staleTurn
        ? proposal && proposal.status !== "confirmed"
          ? proposal
          : prev.proposal
            ? { ...prev.proposal, status: "stale" }
            : null
        : (proposal ?? prev.proposal),
      lastIntent: turn.intent,
      lastStatus: turn.status,
      lastToolCalls: turn.tool_calls,
      requiresHuman: turn.requires_human,
      escalationReason: turn.metadata?.escalation_reason ?? prev.escalationReason,
      conflict: staleTurn
        ? new ApiError(
            409,
            turn.response ||
              "That appointment is no longer available because another confirmation was completed first.",
            turn.status || "stale",
          )
        : prev.conflict,
    }));
    if (turn.shipment_id && turn.shipment_id !== state.shipment?.id) {
      await loadShipment(turn.shipment_id);
    }
  }, [state.shipment?.id]);

  const loadShipment = useCallback(async (shipmentId: string, generation?: number) => {
    boundShipmentId.current = shipmentId;
    const [shipment, latest, etas, exceptions, appointments] = await Promise.all([
      getShipment(shipmentId),
      getLatestEta(shipmentId),
      listShipmentEtaUpdates(shipmentId),
      listShipmentExceptions(shipmentId),
      listShipmentAppointments(shipmentId),
    ]);
    if (boundShipmentId.current !== shipmentId) return;
    const driver = shipment.driver_id ? await getDriver(shipment.driver_id) : null;
    const facility = shipment.destination_facility_id
      ? await getFacility(shipment.destination_facility_id)
      : null;
    const docks = shipment.destination_facility_id
      ? (await listFacilityDocks(shipment.destination_facility_id)).items
      : [];
    const pendingRow = pickPendingProposalAppointment(appointments.items);
    const staleRow = pickStaleProposalAppointment(appointments.items);
    let proposal: Proposal | null = null;
    let conflict: ApiError | null = null;
    const hydrateId = pendingRow?.id ?? staleRow?.id;
    if (hydrateId) {
      try {
        proposal = await getProposal(hydrateId);
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          conflict = error;
        }
      }
    }
    if (!pendingRow && (proposal?.status === "stale" || Boolean(staleRow))) {
      conflict =
        conflict ??
        new ApiError(409, "This option is no longer available. The previously proposed slot was taken.", "stale");
    }
    const currentConfirmed = pickCurrentAppointment(appointments.items);
    if (generation !== undefined && bootstrapGeneration.current !== generation) return;
    if (boundShipmentId.current !== shipmentId) return;
    setState((prev) => {
      let nextProposal = proposal;
      if (!nextProposal && prev.shipment?.id === shipment.id) {
        if (currentConfirmed && prev.proposal?.status === "proposed") {
          nextProposal = null;
        } else {
          nextProposal = prev.proposal;
        }
      }
      return {
        ...prev,
        shipment,
        driver,
        facility,
        latestEta: latest.latest_eta,
        etaHistory: etas.items,
        exceptions: exceptions.items,
        appointments: appointments.items,
        docks,
        proposal: nextProposal,
        conflict: conflict ?? (prev.shipment?.id === shipment.id ? prev.conflict : null),
        loading: false,
        loadingLabel: null,
      };
    });
  }, []);

  const bootstrap = useCallback(async () => {
    const generation = ++bootstrapGeneration.current;
    const isCurrent = () => bootstrapGeneration.current === generation;
    setState((prev) => ({
      ...prev,
      connecting: true,
      connectionError: false,
      healthError: null,
      error: prev.connectionError ? null : prev.error,
    }));
    try {
      await retryBootstrap(
        async () => {
          if (!isCurrent()) {
            throw new ApiError(0, "Bootstrap superseded.", "superseded");
          }
          const health = await getHealth({ timeoutMs: BOOTSTRAP_TIMEOUT_MS });
          const ok = health.status === "ok" && health.service === "setuhaul";
          if (!ok) {
            throw new ApiError(
              0,
              "Connected host is not the SetuHaul API. Set VITE_API_BASE_URL to the uvicorn process running app.main:app.",
              "wrong_host",
            );
          }
          if (!isCurrent()) {
            throw new ApiError(0, "Bootstrap superseded.", "superseded");
          }
          const listed = await listShipments({}, { timeoutMs: BOOTSTRAP_TIMEOUT_MS });
          if (!isCurrent()) {
            throw new ApiError(0, "Bootstrap superseded.", "superseded");
          }
          setState((prev) => ({
            ...prev,
            healthOk: true,
            healthError: null,
            shipments: listed.items,
          }));
          const preferred =
            listed.items.find((item) => item.shipment_number === "SHP-DEMO-001") ??
            listed.items.find((item) => item.shipment_number === "SHP-CHI-5437") ??
            listed.items.find((item) => item.shipment_number === "SH-1024") ??
            listed.items.find((item) => item.driver_id && item.is_active) ??
            listed.items[0];
          const targetId = boundShipmentId.current ?? preferred?.id;
          if (!targetId) {
            throw new ApiError(404, "No shipments found. Seed the demo dataset, then refresh.", "empty_shipments");
          }
          await loadShipment(targetId, generation);
        },
        { isCurrent },
      );
      if (!isCurrent()) return;
      setState((prev) => ({
        ...prev,
        connecting: false,
        connectionError: false,
        healthOk: true,
        healthError: null,
        error: prev.error && /timed out|unreachable|temporarily unavailable/i.test(prev.error) ? null : prev.error,
      }));
    } catch (error) {
      if (!isCurrent()) return;
      const retryable = isRetryableBootstrapError(error);
      const message = error instanceof ApiError ? error.message : "Unable to reach the SetuHaul API.";
      setState((prev) => ({
        ...prev,
        connecting: false,
        connectionError: retryable,
        healthOk: retryable ? prev.healthOk : false,
        healthError: message,
        error: retryable ? prev.error : message,
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
    const shipmentId = state.shipment.id;
    const driverId = state.driver.id;
    const shipmentNumber = state.shipment.shipment_number;
    setState((prev) => {
      if (prev.threadId || prev.shipment?.id !== shipmentId) return prev;
      return { ...prev, loading: true, loadingLabel: "Opening conversation…", error: null };
    });
    try {
      const created = await createConversation({
        driver_id: driverId,
        shipment_id: shipmentId,
        subject: `Driver console · ${shipmentNumber}`,
      });
      if (boundShipmentId.current && boundShipmentId.current !== shipmentId) return;
      setState((prev) => {
        if (prev.shipment?.id !== shipmentId) return prev;
        if (prev.threadId) {
          return { ...prev, conversationReady: true };
        }
        return {
          ...prev,
          threadId: created.thread_id,
          messages: [],
          lastIntent: null,
          lastStatus: created.status,
          conversationReady: true,
        };
      });
    } catch (error) {
      if (boundShipmentId.current && boundShipmentId.current !== shipmentId) return;
      setState((prev) => {
        if (prev.shipment?.id !== shipmentId) return prev;
        return {
          ...prev,
          conversationReady: true,
          error: error instanceof ApiError ? error.message : "Could not create conversation.",
        };
      });
    } finally {
      setState((prev) => (prev.shipment?.id === shipmentId ? { ...prev, loading: false, loadingLabel: null } : prev));
    }
  }, [state.driver, state.shipment]);

  useEffect(() => {
    if (state.driver && state.shipment && !state.threadId && !state.loading && !state.conversationReady) {
      void startConversation();
    }
  }, [state.driver, state.shipment, state.threadId, state.loading, state.conversationReady, startConversation]);

  const hydrateThread = useCallback(async (threadId: string) => {
    const [thread, page] = await Promise.all([getChatThread(threadId), listChatMessages(threadId)]);
    if (thread.shipment_id && boundShipmentId.current && thread.shipment_id !== boundShipmentId.current) {
      setState((prev) => ({
        ...prev,
        threadId: null,
        messages: [],
        conversationReady: false,
      }));
      return;
    }
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
      void hydrateThread(state.threadId).catch((error: unknown) => {
        if (isConversationThreadMissing(error) || (error instanceof ApiError && error.status === 404)) {
          setState((prev) => ({
            ...prev,
            threadId: null,
            conversationReady: false,
          }));
        }
      });
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
    async function loadAppointmentSlots() {
      const original = pickOriginalAppointment(state.appointments);
      const current = pickCurrentAppointment(state.appointments);
      const originalSlot = original?.appointment_slot_id
        ? await getAppointmentSlot(original.appointment_slot_id)
        : null;
      let currentSlot: AppointmentSlot | null = null;
      if (current?.appointment_slot_id) {
        if (current.appointment_slot_id === original?.appointment_slot_id) {
          currentSlot = originalSlot;
        } else {
          currentSlot = await getAppointmentSlot(current.appointment_slot_id);
        }
      }
      if (!cancelled) setState((prev) => ({ ...prev, originalSlot, currentSlot }));
    }
    void loadAppointmentSlots();
    return () => {
      cancelled = true;
    };
  }, [state.appointments]);

  const send = useCallback(
    async (text?: string) => {
      const message = (text ?? state.composer).trim();
      if (!message || !state.driver || !state.shipment) return;
      const kind = /\bconfirm\b|\bbook it\b|\block it in\b/i.test(message) && !/\b(has|have|is).{0,40}confirmed\b/i.test(message)
        ? "confirm"
        : "message";
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
        const result = await sendDriverMessage({
          threadId: state.threadId,
          message,
          driverId: state.driver.id,
          shipmentId: state.shipment.id,
          shipmentNumber: state.shipment.shipment_number,
          createConversation,
          sendConversationMessage,
        });
        setState((prev) => ({
          ...prev,
          threadId: result.threadId,
          conversationReady: true,
        }));
        await applyTurn(result.turn, message);
        await refreshOperational();
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          setState((prev) => ({
            ...prev,
            conflict: new ApiError(
              409,
              "That appointment is no longer available because another confirmation was completed first.",
              error.code,
            ),
          }));
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
    [applyTurn, refreshOperational, state.composer, state.driver, state.shipment, state.threadId],
  );

  const selectOption = useCallback(
    async (option: PresentedOption) => {
      setState((prev) => ({ ...prev, selectedOptionIndex: option.index }));
      await send(`Option ${option.index}`);
    },
    [send],
  );

  const confirmProposal = useCallback(async () => {
    if (!state.proposal) {
      if (state.threadId) await send("Confirm it.");
      return;
    }
    setState((prev) => ({ ...prev, loading: true, loadingLabel: "Revalidating…", confirming: true }));
    try {
      const proposal = await acceptProposal(state.proposal.proposal_id);
      setState((prev) => ({ ...prev, proposal, conflict: null }));
      await refreshOperational();
    } catch (error) {
      if (error instanceof ApiError && (error.status === 409 || /stale|no longer available|conflict/i.test(error.message))) {
        setState((prev) => ({
          ...prev,
          conflict: new ApiError(
            error.status,
            "That appointment is no longer available because another confirmation was completed first.",
            error.code,
          ),
          proposal: prev.proposal ? { ...prev.proposal, status: "stale" } : prev.proposal,
        }));
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

  const selectShipment = useCallback(
    async (shipmentId: string) => {
      if (!shipmentId || shipmentId === state.shipment?.id) return;
      const next = state.shipments.find((item) => item.id === shipmentId) ?? null;
      setState((prev) => ({
        ...prev,
        shipment: next ?? prev.shipment,
        driver: null,
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
        currentSlot: null,
        conflict: null,
        lastIntent: null,
        lastStatus: null,
        lastToolCalls: [],
        requiresHuman: false,
        escalationReason: null,
        conversationReady: false,
        error: null,
        composer: "",
        loading: false,
        loadingLabel: null,
        confirming: false,
      }));
      await loadShipment(shipmentId);
    },
    [loadShipment, state.shipment?.id, state.shipments],
  );

  const originalAppointment = useMemo(() => pickOriginalAppointment(state.appointments), [state.appointments]);
  const currentAppointment = useMemo(() => pickCurrentAppointment(state.appointments), [state.appointments]);
  const rescheduled = useMemo(
    () => Boolean(currentAppointment && hasSupersededHistory(state.appointments)),
    [currentAppointment, state.appointments],
  );

  const value: OpsContextValue = {
    ...state,
    timezone,
    originalAppointment,
    currentAppointment,
    rescheduled,
    setComposer: (composer) => setState((prev) => ({ ...prev, composer })),
    send,
    startConversation,
    refreshOperational,
    selectShipment,
    selectOption,
    confirmProposal,
    rejectCurrentProposal,
    retryBootstrap: bootstrap,
    findNewOptions: () => {
      setState((prev) => ({ ...prev, conflict: null }));
      void send("What options do I have?");
    },
  };

  return <OpsContext.Provider value={value}>{children}</OpsContext.Provider>;
}

export function useOps() {
  const value = useContext(OpsContext);
  if (!value) throw new Error("useOps must be used within OpsProvider");
  return value;
}
