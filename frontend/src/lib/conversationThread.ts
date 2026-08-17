import { ApiError } from "@/api/client";
import type {
  ConversationCreateRequest,
  ConversationCreateResponse,
  ConversationMessageResponse,
} from "@/api/types";

export function isConversationThreadMissing(error: unknown): boolean {
  if (!(error instanceof ApiError) || error.status !== 404) return false;
  return /thread .+ not found|thread not found/i.test(error.message);
}

export interface SendDriverMessageDeps {
  threadId: string | null;
  message: string;
  driverId: string;
  shipmentId: string;
  shipmentNumber?: string | null;
  createConversation: (payload: ConversationCreateRequest) => Promise<ConversationCreateResponse>;
  sendConversationMessage: (threadId: string, message: string) => Promise<ConversationMessageResponse>;
}

export interface SendDriverMessageResult {
  threadId: string;
  turn: ConversationMessageResponse;
  recoveredStaleThread: boolean;
}

function createPayload(deps: SendDriverMessageDeps): ConversationCreateRequest {
  return {
    driver_id: deps.driverId,
    shipment_id: deps.shipmentId,
    subject: `Driver console · ${deps.shipmentNumber ?? deps.shipmentId}`,
  };
}

/**
 * Send one driver message against a live conversation.
 * Missing thread → create, then send.
 * HTTP 404 / thread not found → discard stale id, create once, retry the original message once.
 */
export async function sendDriverMessage(deps: SendDriverMessageDeps): Promise<SendDriverMessageResult> {
  const payload = createPayload(deps);
  let threadId = deps.threadId;
  let recoveredStaleThread = false;

  if (!threadId) {
    const created = await deps.createConversation(payload);
    threadId = created.thread_id;
  }

  try {
    const turn = await deps.sendConversationMessage(threadId, deps.message);
    return { threadId, turn, recoveredStaleThread };
  } catch (error) {
    if (!isConversationThreadMissing(error)) {
      throw error;
    }
    const created = await deps.createConversation(payload);
    threadId = created.thread_id;
    recoveredStaleThread = true;
    const turn = await deps.sendConversationMessage(threadId, deps.message);
    return { threadId, turn, recoveredStaleThread };
  }
}
