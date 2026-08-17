import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/client";
import type { ConversationCreateResponse, ConversationMessageResponse } from "@/api/types";
import { isConversationThreadMissing, sendDriverMessage } from "./conversationThread";

const DRIVER_ID = "driver-1";
const SHIPMENT_ID = "shipment-1";
const MESSAGE = "Running late, ETA 8:30 PM.";

function created(threadId: string): ConversationCreateResponse {
  return {
    thread_id: threadId,
    driver_id: DRIVER_ID,
    shipment_id: SHIPMENT_ID,
    status: "open",
  };
}

function turn(threadId: string, response = "Acknowledged."): ConversationMessageResponse {
  return {
    thread_id: threadId,
    message_id: "msg-1",
    response,
    intent: "UPDATE_ETA",
    status: "ok",
    tool_calls: [],
    requires_clarification: false,
    requires_human: false,
    shipment_id: SHIPMENT_ID,
    proposal_id: null,
  };
}

function threadNotFound(threadId: string) {
  return new ApiError(404, `Chat thread ${threadId} not found`, "http_404");
}

describe("isConversationThreadMissing", () => {
  it("recognizes HTTP 404 thread-not-found errors", () => {
    expect(isConversationThreadMissing(threadNotFound("abc"))).toBe(true);
    expect(isConversationThreadMissing(new ApiError(404, "Conversation thread not found"))).toBe(true);
    expect(isConversationThreadMissing(new ApiError(409, "stale"))).toBe(false);
    expect(isConversationThreadMissing(new ApiError(404, "Shipment missing"))).toBe(false);
  });
});

describe("sendDriverMessage conversation lifecycle", () => {
  it("A. no existing thread → create conversation → send message", async () => {
    const createConversation = vi.fn().mockResolvedValue(created("new-thread"));
    const sendConversationMessage = vi.fn().mockResolvedValue(turn("new-thread"));

    const result = await sendDriverMessage({
      threadId: null,
      message: MESSAGE,
      driverId: DRIVER_ID,
      shipmentId: SHIPMENT_ID,
      shipmentNumber: "SH-1024",
      createConversation,
      sendConversationMessage,
    });

    expect(createConversation).toHaveBeenCalledTimes(1);
    expect(createConversation).toHaveBeenCalledWith({
      driver_id: DRIVER_ID,
      shipment_id: SHIPMENT_ID,
      subject: "Driver console · SH-1024",
    });
    expect(sendConversationMessage).toHaveBeenCalledTimes(1);
    expect(sendConversationMessage).toHaveBeenCalledWith("new-thread", MESSAGE);
    expect(result.threadId).toBe("new-thread");
    expect(result.turn.response).toBe("Acknowledged.");
    expect(result.recoveredStaleThread).toBe(false);
  });

  it("B. existing valid thread → send normally", async () => {
    const createConversation = vi.fn();
    const sendConversationMessage = vi.fn().mockResolvedValue(turn("live-thread"));

    const result = await sendDriverMessage({
      threadId: "live-thread",
      message: MESSAGE,
      driverId: DRIVER_ID,
      shipmentId: SHIPMENT_ID,
      createConversation,
      sendConversationMessage,
    });

    expect(createConversation).not.toHaveBeenCalled();
    expect(sendConversationMessage).toHaveBeenCalledTimes(1);
    expect(sendConversationMessage).toHaveBeenCalledWith("live-thread", MESSAGE);
    expect(result.threadId).toBe("live-thread");
    expect(result.recoveredStaleThread).toBe(false);
  });

  it("C. stale thread → 404 → create new thread → retry once", async () => {
    const createConversation = vi.fn().mockResolvedValue(created("fresh-thread"));
    const sendConversationMessage = vi
      .fn()
      .mockRejectedValueOnce(threadNotFound("stale-thread"))
      .mockResolvedValueOnce(turn("fresh-thread", "Here are options."));

    const result = await sendDriverMessage({
      threadId: "stale-thread",
      message: MESSAGE,
      driverId: DRIVER_ID,
      shipmentId: SHIPMENT_ID,
      createConversation,
      sendConversationMessage,
    });

    expect(createConversation).toHaveBeenCalledTimes(1);
    expect(sendConversationMessage).toHaveBeenCalledTimes(2);
    expect(sendConversationMessage).toHaveBeenNthCalledWith(1, "stale-thread", MESSAGE);
    expect(sendConversationMessage).toHaveBeenNthCalledWith(2, "fresh-thread", MESSAGE);
    expect(result.threadId).toBe("fresh-thread");
    expect(result.turn.response).toBe("Here are options.");
    expect(result.recoveredStaleThread).toBe(true);
  });

  it("D. stale thread cannot cause infinite retries", async () => {
    const createConversation = vi.fn().mockResolvedValue(created("also-missing"));
    const sendConversationMessage = vi.fn().mockRejectedValue(threadNotFound("gone"));

    await expect(
      sendDriverMessage({
        threadId: "stale-thread",
        message: MESSAGE,
        driverId: DRIVER_ID,
        shipmentId: SHIPMENT_ID,
        createConversation,
        sendConversationMessage,
      }),
    ).rejects.toMatchObject({ status: 404 });

    expect(createConversation).toHaveBeenCalledTimes(1);
    expect(sendConversationMessage).toHaveBeenCalledTimes(2);
  });

  it("E. original message is not duplicated on successful recovery", async () => {
    const createConversation = vi.fn().mockResolvedValue(created("fresh-thread"));
    const sendConversationMessage = vi
      .fn()
      .mockRejectedValueOnce(threadNotFound("stale-thread"))
      .mockResolvedValueOnce(turn("fresh-thread"));

    await sendDriverMessage({
      threadId: "stale-thread",
      message: MESSAGE,
      driverId: DRIVER_ID,
      shipmentId: SHIPMENT_ID,
      createConversation,
      sendConversationMessage,
    });

    expect(sendConversationMessage).toHaveBeenCalledTimes(2);
    expect(sendConversationMessage.mock.calls.map((call) => call[1])).toEqual([MESSAGE, MESSAGE]);
    expect(sendConversationMessage.mock.calls.map((call) => call[0])).toEqual(["stale-thread", "fresh-thread"]);
    expect(createConversation).toHaveBeenCalledTimes(1);
  });

  it("does not recreate the thread for non-404 send failures", async () => {
    const createConversation = vi.fn();
    const sendConversationMessage = vi.fn().mockRejectedValue(new ApiError(409, "This option is no longer available."));

    await expect(
      sendDriverMessage({
        threadId: "live-thread",
        message: MESSAGE,
        driverId: DRIVER_ID,
        shipmentId: SHIPMENT_ID,
        createConversation,
        sendConversationMessage,
      }),
    ).rejects.toMatchObject({ status: 409 });

    expect(createConversation).not.toHaveBeenCalled();
    expect(sendConversationMessage).toHaveBeenCalledTimes(1);
  });
});
