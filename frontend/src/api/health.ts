import { apiErrorMessage } from "./client";

export interface MetaResponse {
  app: string;
  version: string;
  environment: string;
  stage: string;
}

export async function fetchMeta(): Promise<MetaResponse> {
  const response = await fetch("/api/v1/meta");
  if (!response.ok) {
    throw new Error(apiErrorMessage(response.status, await response.text()));
  }
  return response.json();
}

export async function fetchDbHealth(): Promise<{ status: string; database: string }> {
  const response = await fetch("/api/v1/health/db");
  if (!response.ok) {
    throw new Error(apiErrorMessage(response.status, await response.text()));
  }
  return response.json();
}
