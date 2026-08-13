import { apiRequest } from "./client";
import type {
  ChatMessage,
  ChatThread,
  ConversationCreateRequest,
  ConversationCreateResponse,
  ConversationMessageResponse,
  Paginated,
} from "./types";

export function createConversation(payload: ConversationCreateRequest) {
  return apiRequest<ConversationCreateResponse>("/conversations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function sendConversationMessage(threadId: string, message: string) {
  return apiRequest<ConversationMessageResponse>(`/conversations/${threadId}/messages`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export function listChatThreads(params: { shipment_id?: string; driver_id?: string } = {}) {
  const query = new URLSearchParams({ page: "1", page_size: "50" });
  if (params.shipment_id) query.set("shipment_id", params.shipment_id);
  if (params.driver_id) query.set("driver_id", params.driver_id);
  return apiRequest<Paginated<ChatThread>>(`/chat-threads?${query.toString()}`);
}

export function getChatThread(threadId: string) {
  return apiRequest<ChatThread>(`/chat-threads/${threadId}`);
}

export function listChatMessages(threadId: string) {
  const query = new URLSearchParams({
    page: "1",
    page_size: "100",
    chat_thread_id: threadId,
  });
  return apiRequest<Paginated<ChatMessage>>(`/chat-messages?${query.toString()}`);
}
