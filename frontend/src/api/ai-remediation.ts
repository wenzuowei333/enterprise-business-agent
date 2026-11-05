import { requestJson } from "./client";

export type RemediationFieldType = "short_text" | "long_text" | "number" | "date" | "datetime" | "boolean" | "single_select" | "multi_select" | "business_reference" | "file";

export type RemediationFormField = {
  field_id: string;
  field_type: RemediationFieldType;
  label: string;
  description: string;
  required: boolean;
  options: Array<{ value: string; label: string }>;
  reference_type?: "import_batch" | "product" | "customer" | "warehouse" | null;
  min_value?: number | null;
  max_value?: number | null;
  max_length?: number | null;
};

export type RemediationFormSchema = {
  schema_version: "remediation-form.v1";
  title: string;
  reason: string;
  fields: RemediationFormField[];
  missing_evidence: string[];
  generation_notes: string[];
};

export type RemediationPlan = {
  schema_version: "remediation-plan.v1";
  summary: string;
  confirmed_facts: string[];
  assumptions: string[];
  steps: string[];
  expected_impact: string;
  verification_steps: string[];
  rollback: string;
  risks: string[];
  missing_information: string[];
  action_candidate: { action_type?: string | null; parameters: Record<string, unknown>; rationale: string };
  sandbox_candidate?: { language: "sql" | "shell" | "http"; purpose: string; code: string } | null;
};

export type RemediationAttachment = {
  attachment_no: string;
  original_name: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  scan_status: string;
  parse_status: string;
  error_code?: string | null;
  created_at: string;
};

export type RemediationWorkflow = {
  workflow_no: string;
  case_no: string;
  source_message_no: string;
  evidence_version: string;
  status: string;
  lock_version: number;
  form_schema?: RemediationFormSchema | null;
  answers: Record<string, unknown>;
  plan?: RemediationPlan | null;
  sandbox: Record<string, unknown>;
  result: Record<string, unknown>;
  error_code?: string | null;
  attachments: RemediationAttachment[];
  can_execute: boolean;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
};

export function createRemediation(sourceMessageNo: string) {
  return requestJson<RemediationWorkflow>("/api/v1/ai/remediations", {
    method: "POST",
    body: JSON.stringify({ source_message_no: sourceMessageNo, client_request_id: crypto.randomUUID() }),
  });
}

export function getRemediation(workflowNo: string) {
  return requestJson<RemediationWorkflow>(`/api/v1/ai/remediations/${encodeURIComponent(workflowNo)}`);
}

export function remediationReferences(workflowNo: string, referenceType: string, query = "") {
  const params = new URLSearchParams({ q: query, limit: "50" });
  return requestJson<Array<{ value: string; label: string }>>(`/api/v1/ai/remediations/${encodeURIComponent(workflowNo)}/references/${encodeURIComponent(referenceType)}?${params}`);
}

export function saveRemediationAnswers(workflow: RemediationWorkflow, answers: Record<string, unknown>) {
  return requestJson<RemediationWorkflow>(`/api/v1/ai/remediations/${encodeURIComponent(workflow.workflow_no)}/answers`, {
    method: "PUT",
    body: JSON.stringify({ expected_lock_version: workflow.lock_version, answers }),
  });
}

export function generateRemediationPlan(workflow: RemediationWorkflow) {
  return requestJson<RemediationWorkflow>(`/api/v1/ai/remediations/${encodeURIComponent(workflow.workflow_no)}/plan`, {
    method: "POST",
    body: JSON.stringify({ expected_lock_version: workflow.lock_version, client_request_id: crypto.randomUUID() }),
  });
}

export function confirmRemediation(workflow: RemediationWorkflow) {
  return requestJson<RemediationWorkflow>(`/api/v1/ai/remediations/${encodeURIComponent(workflow.workflow_no)}/confirm-execute`, {
    method: "POST",
    body: JSON.stringify({ expected_lock_version: workflow.lock_version, confirmation: true, idempotency_key: `remediation:${workflow.workflow_no}:${crypto.randomUUID()}` }),
  });
}

export function cancelRemediation(workflow: RemediationWorkflow) {
  return requestJson<RemediationWorkflow>(`/api/v1/ai/remediations/${encodeURIComponent(workflow.workflow_no)}/cancel`, {
    method: "POST",
    body: JSON.stringify({ expected_lock_version: workflow.lock_version }),
  });
}

export function uploadRemediationAttachment(workflowNo: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  return requestJson<RemediationWorkflow>(`/api/v1/ai/remediations/${encodeURIComponent(workflowNo)}/attachments`, { method: "POST", body: form });
}

export function deleteRemediationAttachment(workflowNo: string, attachmentNo: string) {
  return requestJson<RemediationWorkflow>(`/api/v1/ai/remediations/${encodeURIComponent(workflowNo)}/attachments/${encodeURIComponent(attachmentNo)}`, { method: "DELETE" });
}
