export type CrmProjectStatus = "draft" | "submitted" | "active" | "paused" | "closed" | "cancelled";
export type CrmTaskStatus = "not_started" | "in_progress" | "need_supplement" | "need_support" | "paused" | "closed";
export type CrmReviewStatus = "pending" | "approved" | "rejected" | "need_supplement";
export type ApprovalStatus =
  | "draft"
  | "submitted"
  | "under_review"
  | "need_supplement"
  | "approved"
  | "rejected"
  | "cancelled"
  | "completed";
export type WorkItemStatus = "open" | "processing" | "resolved" | "closed";
export type WorkItemPriority = "normal" | "high" | "urgent";

export interface CrmProject {
  id: number;
  project_code: string;
  project_name: string;
  project_type: string | null;
  business_line: string | null;
  owner_user_id: number | null;
  project_manager_user_id: number | null;
  participant_user_ids: number[] | null;
  start_date: string | null;
  due_date: string | null;
  status: CrmProjectStatus;
  approval_status: ApprovalStatus | string;
  current_approval_id: number | null;
  next_step_status: string | null;
  next_step_action: string | null;
  next_step_followup_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CrmProjectTask {
  id: number;
  project_id: number;
  task_code: string;
  customer_code: string;
  customer_name_snapshot: string;
  executor_user_id: number | null;
  executor_employee_code: string | null;
  executor_name_snapshot: string | null;
  feedback_due_at: string | null;
  status: CrmTaskStatus;
  minimum_action_done: boolean;
  need_support: boolean;
  need_manager_support: boolean;
  need_boss_decision: boolean;
  is_blocked: boolean;
  is_closed: boolean;
  latest_followup_id: number | null;
  last_followup_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CrmFollowup {
  id: number;
  followup_no: string;
  project_id: number;
  task_id: number;
  customer_code: string;
  executor_user_id: number | null;
  followup_date: string | null;
  method: string | null;
  need_support: boolean;
  need_manager_support: boolean;
  need_boss_decision: boolean;
  is_closed: boolean;
  valid_feedback: boolean;
  review_status: CrmReviewStatus;
  approval_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface ApprovalInstance {
  id: number;
  approval_no: string;
  approval_type: string;
  resource_type: string;
  resource_id: string;
  title: string;
  applicant_user_id: number | null;
  current_handler_user_id: number | null;
  status: ApprovalStatus;
  priority: WorkItemPriority;
  submitted_at: string | null;
  reviewed_at: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkItem {
  id: number;
  item_no: string;
  source_type: string;
  source_id: string;
  resource_type: string | null;
  resource_id: string | null;
  project_id: number | null;
  customer_code: string | null;
  item_type: string;
  title: string;
  priority: WorkItemPriority;
  status: WorkItemStatus;
  assignee_user_id: number | null;
  due_at: string | null;
  resolved_by_user_id: number | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}
