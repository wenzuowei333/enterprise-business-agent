import { apiErrorMessage, getToken, requestJson } from "./client";

export type AiChatContext = {
  scope: "current_filters" | "selected_cases" | "case";
  filters: Record<string, string | number | boolean | null>;
  case_nos: string[];
};

export type AiCaseContextMeta = {
  case_no: string;
  title: string;
  severity: string;
  status: string;
  evidence_version?: string;
  evidence_truncated?: boolean;
};

export type AiChatArtifact = {
  type: "exception_case_analysis" | string;
  case?: AiCaseContextMeta;
  action_path?: string | null;
  available_actions?: string[];
  source_refs?: string[];
  evidence_truncated?: boolean;
  remediation_enabled?: boolean;
};

export type AiChatMessage = {
  message_no: string;
  sequence_no: number;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  status: string;
  request_id?: string | null;
  model_name?: string | null;
  source_refs: string[];
  context_meta: Partial<AiCaseContextMeta>;
  artifacts: AiChatArtifact[];
  created_at: string;
};

export type AiChatConversation = {
  conversation_no: string;
  channel: string;
  status: string;
  title: string;
  model_name?: string | null;
  message_count: number;
  last_message: string;
  context_type?: string | null;
  context_id?: string | null;
  operation?: string | null;
  evidence_version?: string | null;
  created_at: string;
  updated_at: string;
};

export type AiChatRun = {
  run_no: string;
  conversation_no: string;
  status: string;
  request_id: string;
  model_name?: string | null;
  usage: Record<string, number | null>;
  error_code?: string | null;
};

export type AiChatStreamEvent = {
  event: string;
  data: Record<string, unknown>;
  id?: string;
};

export function aiChatConversations() {
  return requestJson<AiChatConversation[]>("/api/v1/ai/chat/conversations");
}

export function aiChatMessages(conversationNo: string) {
  return requestJson<AiChatMessage[]>(`/api/v1/ai/chat/conversations/${encodeURIComponent(conversationNo)}/messages`);
}

export function aiChatRun(runNo: string) {
  return requestJson<AiChatRun>(`/api/v1/ai/chat/runs/${encodeURIComponent(runNo)}`);
}

export function cancelAiChatRun(runNo: string) {
  return requestJson<{ run_no: string; status: string }>(`/api/v1/ai/chat/runs/${encodeURIComponent(runNo)}/cancel`, { method: "POST" });
}

export function deleteAiChatConversation(conversationNo: string) {
  return requestJson<{ deleted: boolean }>(`/api/v1/ai/chat/conversations/${encodeURIComponent(conversationNo)}`, { method: "DELETE" });
}

function parseSseFrame(frame: string): AiChatStreamEvent | null {
  let event = "message";
  let id: string | undefined;
  const data: string[] = [];
  for (const rawLine of frame.split("\n")) {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator >= 0 ? line.slice(0, separator) : line;
    const value = separator >= 0 ? line.slice(separator + 1).replace(/^ /, "") : "";
    if (field === "event") event = value;
    else if (field === "id") id = value;
    else if (field === "data") data.push(value);
  }
  if (!data.length) return null;
  const decoded = JSON.parse(data.join("\n")) as Record<string, unknown>;
  return { event, data: decoded, id };
}

export async function streamAiChat(
  payload: {
    client_request_id: string;
    conversation_no: string | null;
    message: string;
    channel: "exception_center_web";
    operation: string;
    context: AiChatContext;
  },
  onEvent: (event: AiChatStreamEvent) => void,
  signal: AbortSignal,
) {
  const headers = new Headers({ "Content-Type": "application/json", Accept: "text/event-stream" });
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch("/api/v1/ai/chat/streams", {
    method: "POST",
    headers,
    credentials: "include",
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(apiErrorMessage(response.status, await response.text()));
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseSseFrame(frame);
      if (parsed) onEvent(parsed);
      boundary = buffer.indexOf("\n\n");
    }
    if (done) break;
  }
  if (buffer.trim()) {
    const parsed = parseSseFrame(buffer);
    if (parsed) onEvent(parsed);
  }
}
