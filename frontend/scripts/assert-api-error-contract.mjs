import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const source = readFileSync(resolve("src/api/client.ts"), "utf8");

const requiredSnippets = [
  "export function apiErrorMessage(status: number, rawBody: string)",
  "status >= 500",
  "服务器暂时不可用，请稍后重试。",
  'detail && typeof detail === "object"',
  "export class ApiError extends Error",
  "error_code?: string | null",
  "request_id?: string | null",
  "action_path?: string | null",
  "field_errors?: Array<",
  "this.field_errors = payload.field_errors ?? []",
  'export const API_ERROR_EVENT = "project-base:api-error";',
  "error.status === 401",
  'path.startsWith("/api/v1/auth/")',
  "detail: { error, method, path }",
  "publishApiError(error, url, options);",
  "CRM lead duplicate acknowledgement required",
  "联系电话与现有线索完全一致，不能重复创建。",
  "throw error;"
];

for (const snippet of requiredSnippets) {
  if (!source.includes(snippet)) {
    throw new Error(`Missing web API error contract: ${snippet}`);
  }
}

const app = readFileSync(resolve("src/App.tsx"), "utf8");
if (!app.includes("apiError?.field_errors.slice(0, 5)") || !app.includes("复制请求编号") || !app.includes("打开处理位置")) {
  throw new Error("Structured Web errors must render field errors, request IDs and action links");
}

if (!app.includes("window.addEventListener(API_ERROR_EVENT, handleApiError)") || !app.includes('data-testid="global-api-error"') || !app.includes('data-testid="api-error-close"')) {
  throw new Error("Structured Web errors must use a dismissible application-wide notice");
}
if (source.includes("detail: { error, method, path, rawBody }") || source.includes("detail: { error, rawBody }")) {
  throw new Error("The global API error event must never expose raw response bodies");
}

for (const forbidden of [
  "throw new Error(text || `HTTP ${response.status}`);",
  "throw new Error(await response.text() || `HTTP ${response.status}`);"
]) {
  if (source.includes(forbidden)) {
    throw new Error(`Web API error contract cannot expose raw HTTP errors: ${forbidden}`);
  }
}

console.log("Web API error contract OK");
