import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Ban,
  Check,
  ChevronRight,
  ClipboardCheck,
  Download,
  FileSpreadsheet,
  History,
  PackageCheck,
  Paperclip,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Send,
  Settings2,
  Tags,
  Truck,
  Upload,
  X,
} from "lucide-react";

import {
  activateCustomerTagCatalogVersion,
  activateCustomerTagRuleVersion,
  cancelSalesOrder,
  confirmSalesOrder,
  createCustomerTagChangeRequest,
  createCustomerTagCatalogDefinition,
  createCustomerTagCatalogVersion,
  createCustomerTagRuleVersion,
  createSalesOrder,
  customerTagHistory,
  customerTagCatalogVersionDefinitions,
  customerTagCatalogVersions,
  customerTagRecommendations,
  customerTagRuleVersions,
  customerTagChangeRequests,
  customerTagGovernanceSettings,
  customerTagLegacyMappings,
  deliveryTasks,
  decideCustomerTagRecommendation,
  downloadDeliveryAttachment,
  importSalesOrders,
  generateCustomerTagRecommendations,
  masterData,
  refreshSalesOrderRequirements,
  replaceCustomerTagCatalogDefinition,
  reviewCustomerTagChangeRequest,
  reviewCustomerTagLegacyMapping,
  salesOrders,
  structuredCustomerTagCatalog,
  structuredCustomerTagProfile,
  structuredTaggedCustomers,
  supplementCustomerTagChangeRequest,
  updateCustomerTagGovernanceSettings,
  updateDeliveryTask,
  uploadDeliveryAttachment,
  type CustomerTagAssignment,
  type CustomerTagChangeRequest,
  type CustomerTagGovernanceSettings,
  type CustomerTagHistory,
  type CustomerTagRecommendation,
  type CustomerTagRuleVersion,
  type CustomerTagCatalogVersion,
  type CustomerTagColorKey,
  type CustomerTagProfile,
  type DeliveryTaskRow,
  type SalesOrderImportResult,
  type SalesOrderLinePayload,
  type SalesOrderRow,
  type StructuredCustomerTag,
  type TaggedCustomerRow,
} from "../api/client";

type PermissionCode = string;
type CustomerTagCategoryKey =
  | "classification"
  | "product_opportunity"
  | "purchase_characteristic"
  | "delivery_requirement";

type LegacyMappingRow = {
  id: number;
  customer_code: string;
  legacy_tag_name: string;
  target_tag_id?: number | null;
  target_tag_name?: string | null;
  confidence?: number | null;
  rationale?: string | null;
  status: string;
};

const CATEGORY_META: Record<string, { label: string; tone: string }> = {
  classification: {
    label: "客户分类",
    tone: "bg-blue-50 text-blue-700 border-blue-200",
  },
  product_opportunity: {
    label: "产品机会",
    tone: "bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200",
  },
  purchase_characteristic: {
    label: "采购特征",
    tone: "bg-cyan-50 text-cyan-800 border-cyan-200",
  },
  delivery_requirement: {
    label: "配送需求",
    tone: "bg-emerald-50 text-emerald-700 border-emerald-200",
  },
};

const statusLabel: Record<string, string> = {
  active: "启用中",
  retired: "已退役",
  submitted: "待审核",
  partially_completed: "部分完成",
  need_supplement: "待补充",
  completed: "已完成",
  rejected: "已拒绝",
  pending: "待安排",
  planned: "已安排",
  delivering: "配送中",
  delivered: "已签收",
  exception: "异常",
  cancelled: "已取消",
  draft: "草稿",
  confirmed: "已确认",
};

function hasPermission(permissions: PermissionCode[], code: string) {
  return permissions.includes(code);
}

function cx(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function formatDate(value?: string | null) {
  if (!value) return "未设置";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("zh-CN", { hour12: false });
}

function formatBytes(value?: number | null) {
  if (value == null) return "未知大小";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function saveBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function StatusPill({ value }: { value: string }) {
  const warning = ["need_supplement", "exception"].includes(value);
  const success = [
    "active",
    "completed",
    "approved",
    "delivered",
    "confirmed",
  ].includes(value);
  return (
    <span
      className={cx(
        "inline-flex min-h-6 items-center rounded border px-2 text-xs font-medium",
        warning
          ? "border-amber-200 bg-amber-50 text-amber-800"
          : success
            ? "border-emerald-200 bg-emerald-50 text-emerald-700"
            : "border-zinc-200 bg-zinc-50 text-zinc-600",
      )}
    >
      {statusLabel[value] ?? value}
    </span>
  );
}

function IconButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="inline-flex size-9 shrink-0 items-center justify-center rounded-md border border-zinc-200 bg-white text-zinc-700 transition hover:border-zinc-400 hover:text-zinc-950 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  );
}

function CommandButton({
  children,
  onClick,
  disabled,
  tone = "default",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  tone?: "default" | "primary" | "danger";
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cx(
        "inline-flex min-h-9 items-center justify-center gap-2 rounded-md border px-3 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40",
        tone === "primary"
          ? "border-zinc-900 bg-zinc-900 text-white hover:bg-zinc-700"
          : tone === "danger"
            ? "border-red-200 bg-white text-red-700 hover:bg-red-50"
            : "border-zinc-200 bg-white text-zinc-700 hover:border-zinc-400",
      )}
    >
      {children}
    </button>
  );
}

function SectionHeader({
  icon,
  title,
  action,
}: {
  icon: ReactNode;
  title: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex min-h-11 items-center justify-between gap-3 border-b border-zinc-200 pb-3">
      <div className="flex min-w-0 items-center gap-2 text-zinc-900">
        {icon}
        <h2 className="truncate text-base font-semibold">{title}</h2>
      </div>
      {action}
    </div>
  );
}

function FeatureState({
  settings,
  feature,
}: {
  settings: CustomerTagGovernanceSettings | null;
  feature:
    | "tag_workflow_enabled"
    | "recommendation_enabled"
    | "fulfillment_enabled";
}) {
  const enabled = Boolean(settings?.[feature]);
  return (
    <span
      className={cx(
        "inline-flex min-h-7 items-center rounded border px-2 text-xs font-medium",
        enabled
          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
          : "border-zinc-200 bg-zinc-50 text-zinc-500",
      )}
    >
      {enabled ? "已启用" : "试点未启用"}
    </span>
  );
}

function CustomerSearch({
  onSelect,
}: {
  onSelect: (customer: {
    customer_code: string;
    customer_name: string;
  }) => void;
}) {
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(false);

  const search = async () => {
    setLoading(true);
    try {
      const result = await masterData("customers", query.trim());
      setRows(result.slice(0, 20));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <label className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3 top-2.5 size-4 text-zinc-400" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && void search()}
            placeholder="客户编号或名称"
            className="h-10 w-full rounded-md border border-zinc-200 bg-white pl-9 pr-3 text-sm outline-none focus:border-zinc-500"
          />
        </label>
        <IconButton
          label="查询客户"
          onClick={() => void search()}
          disabled={loading}
        >
          <Search className="size-4" />
        </IconButton>
      </div>
      {rows.length > 0 ? (
        <div className="max-h-64 divide-y divide-zinc-100 overflow-auto border-y border-zinc-200">
          {rows.map((row) => (
            <button
              key={String(row.customer_code)}
              type="button"
              onClick={() =>
                onSelect({
                  customer_code: String(row.customer_code),
                  customer_name: String(row.customer_name),
                })
              }
              className="flex w-full items-center justify-between gap-3 px-2 py-3 text-left hover:bg-zinc-50"
            >
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-zinc-900">
                  {String(row.customer_name)}
                </span>
                <span className="block truncate text-xs text-zinc-500">
                  {String(row.customer_code)}
                </span>
              </span>
              <ChevronRight className="size-4 shrink-0 text-zinc-400" />
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function AssignmentRow({
  assignment,
  canSubmit,
  onEdit,
  onCancel,
}: {
  assignment: CustomerTagAssignment;
  canSubmit: boolean;
  onEdit: (assignment: CustomerTagAssignment) => void;
  onCancel: (assignment: CustomerTagAssignment) => void;
}) {
  const detailLabels: Record<string, string> = {
    product_category: "产品品类",
    product_name: "具体产品",
    opportunity_status: "机会状态",
    next_action: "下一步",
    plan_date: "计划日期",
    statistics_start: "统计开始",
    statistics_end: "统计结束",
    order_count: "订单次数",
    average_purchase_interval_days: "采购间隔",
    average_order_quantity: "单次采购量",
    manual_result: "人工结果",
    applicable_address: "适用地址",
    applicable_store: "适用门店",
    time_window: "配送时间",
    signer_requirement: "签收要求",
    temperature_requirement: "温度要求",
    acceptance_requirement: "验收要求",
    site_restrictions: "现场限制",
  };
  const details = Object.entries(assignment.details_json ?? {})
    .filter(
      ([key, value]) => detailLabels[key] && value !== null && value !== "",
    )
    .map(([key, value]) => `${detailLabels[key]}：${String(value)}`);
  return (
    <div className="grid gap-3 border-b border-zinc-100 py-4 last:border-b-0 md:grid-cols-[minmax(160px,0.7fr)_minmax(240px,1.3fr)_auto]">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-zinc-900">
            {assignment.tag_name}
          </span>
          {assignment.is_primary ? (
            <span className="rounded border border-zinc-200 px-1.5 text-[11px] text-zinc-600">
              主要
            </span>
          ) : null}
        </div>
        <div className="mt-1 text-xs text-zinc-500">
          {assignment.group_name ?? "一级分类"} ·{" "}
          {assignment.attribute_type === "temporary" ? "临时" : "长期"}
        </div>
      </div>
      <div className="min-w-0 text-sm text-zinc-600">
        <p className="break-words">{assignment.evidence}</p>
        {details.length ? (
          <p className="mt-1 break-words text-xs text-zinc-500">
            {details.join(" · ")}
          </p>
        ) : null}
        <p className="mt-1 text-xs text-zinc-400">
          复核：{assignment.review_date ?? "长期有效"} · 责任人：
          {assignment.owner_user_label ?? assignment.owner_user_id ?? "未设置"}
        </p>
      </div>
      {canSubmit ? (
        <div className="flex gap-1">
          <IconButton label="申请修改标签" onClick={() => onEdit(assignment)}>
            <Pencil className="size-4" />
          </IconButton>
          <IconButton label="申请取消标签" onClick={() => onCancel(assignment)}>
            <X className="size-4" />
          </IconButton>
        </div>
      ) : null}
    </div>
  );
}

type CategoryDetails = Record<string, string | boolean>;

function categoryDetailsPayload(
  tag: StructuredCustomerTag,
  details: CategoryDetails,
) {
  if (tag.category_key === "product_opportunity") {
    return {
      ...details,
      opportunity_status: details.opportunity_status || "pending",
    };
  }
  if (tag.category_key === "purchase_characteristic") {
    return {
      ...details,
      system_result: details.system_result || tag.name,
      manual_result: details.manual_result || tag.name,
    };
  }
  if (tag.category_key === "delivery_requirement") {
    return { ...details, auto_apply: details.auto_apply !== false };
  }
  return {};
}

function categoryDetailsComplete(
  tag: StructuredCustomerTag | undefined,
  details: CategoryDetails,
  ownerId: string,
) {
  if (!tag) return false;
  if (tag.category_key === "product_opportunity") {
    const required = [
      "product_category",
      "product_name",
      "opportunity_note",
      "next_action",
      "plan_date",
    ];
    return Boolean(
      ownerId &&
        required.every((key) => String(details[key] ?? "").trim()) &&
        ((details.opportunity_status || "pending") !== "lost" ||
          String(details.invalid_reason ?? "").trim()),
    );
  }
  if (tag.category_key === "purchase_characteristic") {
    return [
      "statistics_start",
      "statistics_end",
      "order_count",
      "average_purchase_interval_days",
      "average_order_quantity",
    ].every((key) => String(details[key] ?? "").trim());
  }
  return true;
}

function CategoryDetailsFields({
  tag,
  details,
  onChange,
}: {
  tag: StructuredCustomerTag | undefined;
  details: CategoryDetails;
  onChange: (details: CategoryDetails) => void;
}) {
  if (!tag) return null;
  const update = (key: string, value: string | boolean) =>
    onChange({ ...details, [key]: value });
  const inputClass = "h-10 w-full rounded-md border border-zinc-200 px-3";
  if (tag.category_key === "product_opportunity") {
    const opportunityStatus = String(details.opportunity_status || "pending");
    return (
      <div className="grid gap-3 border-y border-zinc-100 py-4 md:grid-cols-2 xl:grid-cols-3">
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">产品品类 *</span>
          <input
            value={String(details.product_category ?? "")}
            onChange={(event) => update("product_category", event.target.value)}
            className={inputClass}
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">具体产品 *</span>
          <input
            value={String(details.product_name ?? "")}
            onChange={(event) => update("product_name", event.target.value)}
            className={inputClass}
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">机会状态 *</span>
          <select
            value={opportunityStatus}
            onChange={(event) =>
              update("opportunity_status", event.target.value)
            }
            className={`${inputClass} bg-white`}
          >
            <option value="pending">待推进</option>
            <option value="engaging">推进中</option>
            <option value="won">已成交</option>
            <option value="lost">已失效</option>
          </select>
        </label>
        <label className="space-y-1 text-sm md:col-span-2">
          <span className="text-zinc-600">机会说明 *</span>
          <input
            value={String(details.opportunity_note ?? "")}
            onChange={(event) => update("opportunity_note", event.target.value)}
            className={inputClass}
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">下一步动作 *</span>
          <input
            value={String(details.next_action ?? "")}
            onChange={(event) => update("next_action", event.target.value)}
            className={inputClass}
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">计划日期 *</span>
          <input
            type="date"
            value={String(details.plan_date ?? "")}
            onChange={(event) => update("plan_date", event.target.value)}
            className={inputClass}
          />
        </label>
        {opportunityStatus === "lost" ? (
          <label className="space-y-1 text-sm md:col-span-2">
            <span className="text-zinc-600">失效原因 *</span>
            <input
              value={String(details.invalid_reason ?? "")}
              onChange={(event) => update("invalid_reason", event.target.value)}
              className={inputClass}
            />
          </label>
        ) : null}
      </div>
    );
  }
  if (tag.category_key === "purchase_characteristic") {
    return (
      <div className="grid gap-3 border-y border-zinc-100 py-4 md:grid-cols-2 xl:grid-cols-3">
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">统计开始 *</span>
          <input
            type="date"
            value={String(details.statistics_start ?? "")}
            onChange={(event) => update("statistics_start", event.target.value)}
            className={inputClass}
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">统计结束 *</span>
          <input
            type="date"
            value={String(details.statistics_end ?? "")}
            onChange={(event) => update("statistics_end", event.target.value)}
            className={inputClass}
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">订单次数 *</span>
          <input
            type="number"
            min="1"
            value={String(details.order_count ?? "")}
            onChange={(event) => update("order_count", event.target.value)}
            className={inputClass}
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">平均采购间隔（天）*</span>
          <input
            type="number"
            min="0"
            step="0.1"
            value={String(details.average_purchase_interval_days ?? "")}
            onChange={(event) =>
              update("average_purchase_interval_days", event.target.value)
            }
            className={inputClass}
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">平均单次采购量 *</span>
          <input
            type="number"
            min="0"
            step="0.0001"
            value={String(details.average_order_quantity ?? "")}
            onChange={(event) =>
              update("average_order_quantity", event.target.value)
            }
            className={inputClass}
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">系统结果</span>
          <input
            value={String(details.system_result ?? tag.name)}
            onChange={(event) => update("system_result", event.target.value)}
            className={inputClass}
          />
        </label>
        <label className="space-y-1 text-sm md:col-span-2">
          <span className="text-zinc-600">人工确认结果 *</span>
          <input
            value={String(details.manual_result ?? tag.name)}
            onChange={(event) => update("manual_result", event.target.value)}
            className={inputClass}
          />
        </label>
      </div>
    );
  }
  if (tag.category_key === "delivery_requirement") {
    return (
      <div className="grid gap-3 border-y border-zinc-100 py-4 md:grid-cols-2 xl:grid-cols-3">
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">适用地址</span>
          <input
            value={String(details.applicable_address ?? "")}
            onChange={(event) =>
              update("applicable_address", event.target.value)
            }
            className={inputClass}
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">适用门店</span>
          <input
            value={String(details.applicable_store ?? "")}
            onChange={(event) => update("applicable_store", event.target.value)}
            className={inputClass}
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">配送时间</span>
          <input
            value={String(details.time_window ?? "")}
            onChange={(event) => update("time_window", event.target.value)}
            className={inputClass}
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">签收要求</span>
          <input
            value={String(details.signer_requirement ?? "")}
            onChange={(event) =>
              update("signer_requirement", event.target.value)
            }
            className={inputClass}
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">温度要求</span>
          <input
            value={String(details.temperature_requirement ?? "")}
            onChange={(event) =>
              update("temperature_requirement", event.target.value)
            }
            className={inputClass}
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">验收要求</span>
          <input
            value={String(details.acceptance_requirement ?? "")}
            onChange={(event) =>
              update("acceptance_requirement", event.target.value)
            }
            className={inputClass}
          />
        </label>
        <label className="space-y-1 text-sm md:col-span-2">
          <span className="text-zinc-600">现场限制</span>
          <input
            value={String(details.site_restrictions ?? "")}
            onChange={(event) =>
              update("site_restrictions", event.target.value)
            }
            className={inputClass}
          />
        </label>
        <label className="flex min-h-10 items-center gap-2 pt-6 text-sm text-zinc-700">
          <input
            type="checkbox"
            checked={details.auto_apply !== false}
            onChange={(event) => update("auto_apply", event.target.checked)}
          />
          订单确认时自动带入
        </label>
      </div>
    );
  }
  return null;
}

function TagApplicationForm({
  customer,
  catalog,
  settings,
  assignment,
  onSaved,
  onCancelEdit,
}: {
  customer: { customer_code: string; customer_name: string };
  catalog: StructuredCustomerTag[];
  settings: CustomerTagGovernanceSettings | null;
  assignment?: CustomerTagAssignment | null;
  onSaved: () => void;
  onCancelEdit?: () => void;
}) {
  const [tagId, setTagId] = useState("");
  const [evidence, setEvidence] = useState("");
  const [reviewDate, setReviewDate] = useState("");
  const [ownerId, setOwnerId] = useState("");
  const [primary, setPrimary] = useState(false);
  const [details, setDetails] = useState<CategoryDetails>({});
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const tag = catalog.find((item) => item.id === Number(tagId));
  const needsReviewDate =
    tag?.category_key === "product_opportunity" ||
    tag?.category_key === "purchase_characteristic";
  const detailsComplete = categoryDetailsComplete(tag, details, ownerId);

  useEffect(() => {
    if (!assignment) return;
    setTagId(String(assignment.tag_id));
    setEvidence(assignment.evidence);
    setReviewDate(assignment.review_date ?? "");
    setOwnerId(
      assignment.owner_user_id ? String(assignment.owner_user_id) : "",
    );
    setPrimary(assignment.is_primary);
    setDetails((assignment.details_json ?? {}) as CategoryDetails);
  }, [assignment?.id]);

  const cancelEdit = () => {
    setTagId("");
    setEvidence("");
    setReviewDate("");
    setOwnerId("");
    setPrimary(false);
    setDetails({});
    onCancelEdit?.();
  };

  const submit = async () => {
    if (!tag || !evidence.trim()) return;
    setSaving(true);
    setError("");
    try {
      await createCustomerTagChangeRequest({
        customer_code: customer.customer_code,
        reason: "客户标签资料更新",
        items: [
          {
            action: assignment ? "update" : "add",
            assignment_id: assignment?.id,
            tag_id: tag.id,
            evidence: evidence.trim(),
            review_date: reviewDate || null,
            owner_user_id: ownerId ? Number(ownerId) : null,
            is_primary: primary,
            details_json: categoryDetailsPayload(tag, details),
          },
        ],
      });
      setTagId("");
      setEvidence("");
      setReviewDate("");
      setOwnerId("");
      setPrimary(false);
      setDetails({});
      onCancelEdit?.();
      onSaved();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "提交失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4 border-t border-zinc-200 pt-4">
      {assignment ? (
        <div className="flex items-center justify-between gap-3 border-l-2 border-blue-400 bg-blue-50 px-3 py-2 text-sm text-blue-800">
          <span>正在申请修改：{assignment.tag_name}</span>
          <IconButton label="退出修改" onClick={cancelEdit}>
            <X className="size-4" />
          </IconButton>
        </div>
      ) : null}
      <div className="grid gap-3 lg:grid-cols-2">
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">正式标签</span>
          <select
            value={tagId}
            onChange={(event) => {
              setTagId(event.target.value);
              setDetails({});
              setPrimary(false);
            }}
            className="h-10 w-full rounded-md border border-zinc-200 bg-white px-3"
          >
            <option value="">请选择</option>
            {catalog.map((item) => (
              <option key={item.id} value={item.id}>
                {item.category_name} / {item.group_name ?? "一级分类"} /{" "}
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">
            复核日期{needsReviewDate ? " *" : ""}
          </span>
          <input
            type="date"
            value={reviewDate}
            onChange={(event) => setReviewDate(event.target.value)}
            className="h-10 w-full rounded-md border border-zinc-200 px-3"
          />
        </label>
      </div>
      <label className="block space-y-1 text-sm">
        <span className="text-zinc-600">事实依据</span>
        <textarea
          value={evidence}
          onChange={(event) => setEvidence(event.target.value)}
          rows={3}
          className="w-full resize-y rounded-md border border-zinc-200 px-3 py-2 outline-none focus:border-zinc-500"
        />
      </label>
      <div className="grid gap-3 lg:grid-cols-2">
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">责任人 ID</span>
          <input
            inputMode="numeric"
            value={ownerId}
            onChange={(event) =>
              setOwnerId(event.target.value.replace(/\D/g, ""))
            }
            className="h-10 w-full rounded-md border border-zinc-200 px-3"
          />
        </label>
        {tag?.category_key === "purchase_characteristic" ? (
          <label className="flex min-h-10 items-center gap-2 pt-6 text-sm text-zinc-700">
            <input
              type="checkbox"
              checked={primary}
              onChange={(event) => setPrimary(event.target.checked)}
            />
            设为本组主要标签
          </label>
        ) : null}
      </div>
      <CategoryDetailsFields
        tag={tag}
        details={details}
        onChange={setDetails}
      />
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
      <div className="flex items-center justify-between gap-3">
        <FeatureState settings={settings} feature="tag_workflow_enabled" />
        <CommandButton
          tone="primary"
          disabled={
            saving ||
            !settings?.tag_workflow_enabled ||
            !tagId ||
            !evidence.trim() ||
            (needsReviewDate && !reviewDate) ||
            !detailsComplete
          }
          onClick={() => void submit()}
        >
          <Send className="size-4" />
          {assignment ? "提交修改审核" : "提交审核"}
        </CommandButton>
      </div>
    </div>
  );
}

function LegacyMappingReviewForm({
  mapping,
  catalog,
  onSaved,
  onClose,
}: {
  mapping: LegacyMappingRow;
  catalog: StructuredCustomerTag[];
  onSaved: () => void;
  onClose: () => void;
}) {
  const [tagId, setTagId] = useState(String(mapping.target_tag_id ?? ""));
  const [attributeType, setAttributeType] = useState<"long_term" | "temporary">(
    "long_term",
  );
  const [evidence, setEvidence] = useState(
    mapping.rationale ?? "历史标签人工复核",
  );
  const [reviewDate, setReviewDate] = useState("");
  const [ownerId, setOwnerId] = useState("");
  const [primary, setPrimary] = useState(false);
  const [details, setDetails] = useState<CategoryDetails>({});
  const [orderNo, setOrderNo] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const tag = catalog.find((item) => item.id === Number(tagId));
  const supportsTemporary = Boolean(
    (
      tag?.applicability_json?.attribute_types as unknown[] | undefined
    )?.includes("temporary"),
  );
  const needsReviewDate =
    tag?.category_key === "product_opportunity" ||
    tag?.category_key === "purchase_characteristic";
  const categoryFieldsComplete = categoryDetailsComplete(tag, details, ownerId);
  const temporaryFieldsComplete =
    attributeType !== "temporary" || Boolean(orderNo.trim());

  const submit = async () => {
    if (!tag || !evidence.trim()) return;
    setSaving(true);
    setError("");
    try {
      await reviewCustomerTagLegacyMapping(mapping.id, {
        decision: "submit",
        target_tag_id: tag.id,
        evidence: evidence.trim(),
        attribute_type: attributeType,
        review_date: reviewDate || null,
        owner_user_id: ownerId ? Number(ownerId) : null,
        is_primary: primary,
        details_json: {
          ...categoryDetailsPayload(tag, details),
          ...(attributeType === "temporary"
            ? { order_no: orderNo.trim() }
            : {}),
        },
      });
      onSaved();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "提交失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <aside className="space-y-4 border-l border-zinc-200 pl-5">
      <SectionHeader
        icon={<History className="size-4" />}
        title="结构化复核"
        action={
          <IconButton label="关闭复核" onClick={onClose}>
            <X className="size-4" />
          </IconButton>
        }
      />
      <div>
        <p className="text-sm font-medium text-zinc-900">
          {mapping.legacy_tag_name}
        </p>
        <p className="mt-1 text-xs text-zinc-500">{mapping.customer_code}</p>
      </div>
      <label className="block space-y-1 text-sm">
        <span className="text-zinc-600">目标正式标签</span>
        <select
          value={tagId}
          onChange={(event) => {
            setTagId(event.target.value);
            setAttributeType("long_term");
            setDetails({});
          }}
          className="h-10 w-full rounded-md border border-zinc-200 bg-white px-3"
        >
          <option value="">请选择</option>
          {catalog.map((item) => (
            <option key={item.id} value={item.id}>
              {item.category_name} / {item.group_name ?? "一级分类"} /{" "}
              {item.name}
            </option>
          ))}
        </select>
      </label>
      {supportsTemporary ? (
        <label className="block space-y-1 text-sm">
          <span className="text-zinc-600">有效属性</span>
          <select
            value={attributeType}
            onChange={(event) =>
              setAttributeType(event.target.value as "long_term" | "temporary")
            }
            className="h-10 w-full rounded-md border border-zinc-200 bg-white px-3"
          >
            <option value="long_term">长期</option>
            <option value="temporary">临时</option>
          </select>
        </label>
      ) : null}
      <label className="block space-y-1 text-sm">
        <span className="text-zinc-600">事实依据</span>
        <textarea
          value={evidence}
          onChange={(event) => setEvidence(event.target.value)}
          rows={3}
          className="w-full rounded-md border border-zinc-200 px-3 py-2"
        />
      </label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">
            责任人 ID{tag?.category_key === "product_opportunity" ? " *" : ""}
          </span>
          <input
            inputMode="numeric"
            value={ownerId}
            onChange={(event) =>
              setOwnerId(event.target.value.replace(/\D/g, ""))
            }
            className="h-10 w-full rounded-md border border-zinc-200 px-3"
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-zinc-600">
            复核日期{needsReviewDate ? " *" : ""}
          </span>
          <input
            type="date"
            value={reviewDate}
            onChange={(event) => setReviewDate(event.target.value)}
            className="h-10 w-full rounded-md border border-zinc-200 px-3"
          />
        </label>
      </div>
      {tag?.category_key === "purchase_characteristic" ? (
        <label className="flex items-center gap-2 text-sm text-zinc-700">
          <input
            type="checkbox"
            checked={primary}
            onChange={(event) => setPrimary(event.target.checked)}
          />
          设为本组主要标签
        </label>
      ) : null}
      <CategoryDetailsFields
        tag={tag}
        details={details}
        onChange={setDetails}
      />
      {attributeType === "temporary" ? (
        <label className="block space-y-1 text-sm">
          <span className="text-zinc-600">绑定订单号 *</span>
          <input
            value={orderNo}
            onChange={(event) => setOrderNo(event.target.value)}
            className="h-10 w-full rounded-md border border-zinc-200 px-3"
          />
        </label>
      ) : null}
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
      <CommandButton
        tone="primary"
        disabled={
          saving ||
          !tag ||
          !evidence.trim() ||
          (needsReviewDate && !reviewDate) ||
          !categoryFieldsComplete ||
          !temporaryFieldsComplete
        }
        onClick={() => void submit()}
      >
        <Send className="size-4" />
        提交审核
      </CommandButton>
    </aside>
  );
}

function TaggedCustomerBrowser({
  catalog,
  canExport,
  onOpen,
}: {
  catalog: StructuredCustomerTag[];
  canExport: boolean;
  onOpen: (customer: { customer_code: string; customer_name: string }) => void;
}) {
  const [rows, setRows] = useState<TaggedCustomerRow[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [categoryKey, setCategoryKey] = useState("");
  const [groupCode, setGroupCode] = useState("");
  const [tagId, setTagId] = useState("");
  const [status, setStatus] = useState("effective");
  const [ownerId, setOwnerId] = useState("");
  const [reviewFrom, setReviewFrom] = useState("");
  const [reviewTo, setReviewTo] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const groups = useMemo(
    () =>
      Array.from(
        new Map(
          catalog
            .filter((item) => !categoryKey || item.category_key === categoryKey)
            .filter((item) => item.group_code)
            .map((item) => [
              item.group_code,
              item.group_name ?? item.group_code,
            ]),
        ).entries(),
      ),
    [catalog, categoryKey],
  );
  const tags = useMemo(
    () =>
      catalog.filter(
        (item) =>
          (!categoryKey || item.category_key === categoryKey) &&
          (!groupCode || item.group_code === groupCode),
      ),
    [catalog, categoryKey, groupCode],
  );
  const options = () => ({
    q: query.trim() || undefined,
    categoryKey: categoryKey || undefined,
    groupCode: groupCode || undefined,
    tagIds: tagId ? [Number(tagId)] : undefined,
    assignmentStatus: status || undefined,
    ownerUserId: ownerId ? Number(ownerId) : undefined,
    reviewDateFrom: reviewFrom || undefined,
    reviewDateTo: reviewTo || undefined,
  });
  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const page = await structuredTaggedCustomers(options());
      setRows(page.items);
      setTotal(page.total);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void load();
  }, []);
  const exportUrl = () => {
    const params = new URLSearchParams();
    if (categoryKey) params.set("category_key", categoryKey);
    if (groupCode) params.set("group_code", groupCode);
    if (tagId) params.set("tag_ids", tagId);
    if (status) params.set("status_value", status);
    if (ownerId) params.set("owner_user_id", ownerId);
    if (reviewFrom) params.set("review_date_from", reviewFrom);
    if (reviewTo) params.set("review_date_to", reviewTo);
    return `/api/v1/customer-tagging/export?${params}`;
  };
  return (
    <div className="space-y-5">
      <SectionHeader
        icon={<Search className="size-4" />}
        title={`标签客户 · ${total}`}
        action={
          <div className="flex gap-2">
            {canExport ? (
              <a
                href={exportUrl()}
                download
                className="inline-flex size-9 items-center justify-center rounded-md border border-zinc-200 bg-white text-zinc-700"
                title="导出当前标签数据"
              >
                <Download className="size-4" />
              </a>
            ) : null}
            <IconButton
              label="查询"
              onClick={() => void load()}
              disabled={loading}
            >
              <Search className={cx("size-4", loading && "animate-pulse")} />
            </IconButton>
          </div>
        }
      />
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && void load()}
          placeholder="客户编号或名称"
          className="h-10 rounded-md border border-zinc-200 px-3 text-sm"
        />
        <select
          value={categoryKey}
          onChange={(event) => {
            setCategoryKey(event.target.value);
            setGroupCode("");
            setTagId("");
          }}
          className="h-10 rounded-md border border-zinc-200 bg-white px-3 text-sm"
        >
          <option value="">全部大类</option>
          {Object.entries(CATEGORY_META).map(([key, meta]) => (
            <option key={key} value={key}>
              {meta.label}
            </option>
          ))}
        </select>
        <select
          value={groupCode}
          onChange={(event) => {
            setGroupCode(event.target.value);
            setTagId("");
          }}
          className="h-10 rounded-md border border-zinc-200 bg-white px-3 text-sm"
        >
          <option value="">全部分组</option>
          {groups.map(([code, name]) => (
            <option key={code ?? "classification"} value={code ?? ""}>
              {name}
            </option>
          ))}
        </select>
        <select
          value={tagId}
          onChange={(event) => setTagId(event.target.value)}
          className="h-10 rounded-md border border-zinc-200 bg-white px-3 text-sm"
        >
          <option value="">全部标签</option>
          {tags.map((tag) => (
            <option key={tag.id} value={tag.id}>
              {tag.name}
            </option>
          ))}
        </select>
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="h-10 rounded-md border border-zinc-200 bg-white px-3 text-sm"
        >
          <option value="effective">当前有效</option>
          <option value="expired">已过期</option>
          <option value="cancelled">已取消</option>
          <option value="superseded">已替换</option>
          <option value="">全部状态</option>
        </select>
        <input
          inputMode="numeric"
          value={ownerId}
          onChange={(event) =>
            setOwnerId(event.target.value.replace(/\D/g, ""))
          }
          placeholder="责任人 ID"
          className="h-10 rounded-md border border-zinc-200 px-3 text-sm"
        />
        <input
          type="date"
          value={reviewFrom}
          onChange={(event) => setReviewFrom(event.target.value)}
          className="h-10 rounded-md border border-zinc-200 px-3 text-sm"
          title="复核日期起"
        />
        <input
          type="date"
          value={reviewTo}
          onChange={(event) => setReviewTo(event.target.value)}
          className="h-10 rounded-md border border-zinc-200 px-3 text-sm"
          title="复核日期止"
        />
      </div>
      {error ? (
        <div className="border-l-2 border-red-500 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      ) : null}
      <div className="divide-y divide-zinc-200 border-y border-zinc-200">
        {rows.map((row) => (
          <button
            key={row.customer_code}
            type="button"
            onClick={() => onOpen(row)}
            className="grid w-full gap-3 py-4 text-left hover:bg-zinc-50 md:grid-cols-[minmax(180px,0.7fr)_minmax(280px,1.5fr)_160px_auto]"
          >
            <div>
              <p className="text-sm font-medium text-zinc-900">
                {row.customer_name}
              </p>
              <p className="mt-1 text-xs text-zinc-500">{row.customer_code}</p>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {row.assignments.map((item) => (
                <span
                  key={item.assignment_id}
                  className="rounded border border-zinc-200 px-2 py-1 text-xs text-zinc-600"
                >
                  {item.tag_name}
                  {item.is_primary ? " · 主要" : ""}
                </span>
              ))}
            </div>
            <div className="text-xs text-zinc-500">
              <p>{row.region ?? "未设置区域"}</p>
              <p className="mt-1">{row.salesperson_name ?? "未设置销售"}</p>
            </div>
            <ChevronRight className="size-4 text-zinc-400" />
          </button>
        ))}
        {!loading && rows.length === 0 ? (
          <div className="py-16 text-center text-sm text-zinc-400">
            暂无符合条件的客户
          </div>
        ) : null}
      </div>
    </div>
  );
}

function CustomerTagHistoryTimeline({ data }: { data: CustomerTagHistory }) {
  const events = [
    ...data.profile.assignments.map((assignment) => ({
      key: `assignment-${assignment.id}`,
      at: assignment.created_at,
      title: `${assignment.tag_name ?? "标签"} · ${statusLabel[assignment.status] ?? assignment.status}`,
      detail: `${assignment.category_name ?? "历史标签"} / ${assignment.group_name ?? "一级分类"} · ${assignment.evidence}`,
      status: assignment.status,
    })),
    ...data.requests.map((request) => ({
      key: `request-${request.id}`,
      at: request.submitted_at ?? request.created_at,
      title: `${request.request_no} · ${statusLabel[request.status] ?? request.status}`,
      detail: `${request.applicant_user_label ?? "申请人未记录"}提交 ${request.items.length} 项变更${request.reason ? ` · ${request.reason}` : ""}`,
      status: request.status,
    })),
  ].sort(
    (left, right) => new Date(right.at).getTime() - new Date(left.at).getTime(),
  );

  return (
    <div className="py-5">
      {events.length > 0 ? (
        <ol className="ml-2 border-l border-zinc-200">
          {events.map((event) => (
            <li
              key={event.key}
              className="relative grid gap-2 pb-6 pl-6 last:pb-0 md:grid-cols-[170px_minmax(0,1fr)_auto]"
            >
              <span className="absolute -left-1.5 top-1 size-3 rounded-full border-2 border-white bg-zinc-400" />
              <time className="text-xs text-zinc-400">
                {formatDate(event.at)}
              </time>
              <div className="min-w-0">
                <p className="text-sm font-medium text-zinc-900">
                  {event.title}
                </p>
                <p className="mt-1 break-words text-sm text-zinc-600">
                  {event.detail}
                </p>
              </div>
              <StatusPill value={event.status} />
            </li>
          ))}
        </ol>
      ) : (
        <div className="py-16 text-center text-sm text-zinc-400">
          暂无标签历史
        </div>
      )}
    </div>
  );
}

function CustomerTagRecommendationWorkspace({
  canManage,
  canSubmit,
  enabled,
}: {
  canManage: boolean;
  canSubmit: boolean;
  enabled: boolean;
}) {
  const [rules, setRules] = useState<CustomerTagRuleVersion[]>([]);
  const [rows, setRows] = useState<CustomerTagRecommendation[]>([]);
  const [customerCode, setCustomerCode] = useState("");
  const [ruleName, setRuleName] = useState("采购特征推荐规则");
  const [windowDays, setWindowDays] = useState("180");
  const [frequencyDays, setFrequencyDays] = useState("7");
  const [quantity, setQuantity] = useState("50");
  const [stability, setStability] = useState("0.35");
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = async () => {
    const [nextRules, nextRows] = await Promise.all([
      canManage ? customerTagRuleVersions() : Promise.resolve([]),
      customerTagRecommendations({
        customerCode: customerCode.trim() || undefined,
        status: "pending",
      }),
    ]);
    setRules(nextRules);
    setRows(nextRows);
  };
  useEffect(() => {
    void load().catch((reason) =>
      setError(reason instanceof Error ? reason.message : "推荐数据加载失败"),
    );
  }, []);
  const createRule = async () => {
    setBusy(true);
    setError("");
    try {
      await createCustomerTagRuleVersion({
        rule_code: "purchase_characteristic",
        name: ruleName.trim(),
        parameters_json: {
          window_days: Number(windowDays),
          high_frequency_days: Number(frequencyDays),
          high_quantity: Number(quantity),
          stability_cv: Number(stability),
        },
      });
      setRules(await customerTagRuleVersions());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "规则创建失败");
    } finally {
      setBusy(false);
    }
  };
  const activateRule = async (ruleId: number) => {
    setBusy(true);
    setError("");
    try {
      await activateCustomerTagRuleVersion(ruleId);
      setRules(await customerTagRuleVersions());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "规则激活失败");
    } finally {
      setBusy(false);
    }
  };
  const generate = async () => {
    setBusy(true);
    setError("");
    try {
      await generateCustomerTagRecommendations(
        customerCode.trim() || undefined,
      );
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "推荐生成失败");
    } finally {
      setBusy(false);
    }
  };
  const decide = async (
    row: CustomerTagRecommendation,
    decision: "accept" | "reject",
  ) => {
    const note = notes[row.id]?.trim();
    if (!note) return;
    setBusy(true);
    setError("");
    try {
      await decideCustomerTagRecommendation(row.id, {
        decision,
        manual_result: row.tag_name,
        manual_note: note,
      });
      setNotes((current) => ({ ...current, [row.id]: "" }));
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "推荐处理失败");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-5">
      <SectionHeader
        icon={<RefreshCw className="size-4" />}
        title={`采购特征推荐 · ${rows.length}`}
        action={
          <IconButton
            label="刷新推荐"
            disabled={busy}
            onClick={() => void load()}
          >
            <RefreshCw className={cx("size-4", busy && "animate-spin")} />
          </IconButton>
        }
      />
      {error ? (
        <div className="border-l-2 border-red-500 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <input
          value={customerCode}
          onChange={(event) => setCustomerCode(event.target.value)}
          placeholder="客户编号（可选）"
          className="h-10 min-w-[220px] flex-1 rounded-md border border-zinc-200 px-3 text-sm"
        />
        <CommandButton onClick={() => void load()}>
          <Search className="size-4" />
          查询
        </CommandButton>
        {canManage ? (
          <CommandButton
            tone="primary"
            disabled={busy || !enabled}
            onClick={() => void generate()}
          >
            <RefreshCw className="size-4" />
            生成推荐
          </CommandButton>
        ) : null}
      </div>
      {canManage ? (
        <section className="space-y-3 border-y border-zinc-200 py-4">
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-5">
            <input
              value={ruleName}
              onChange={(event) => setRuleName(event.target.value)}
              placeholder="规则名称"
              className="h-9 rounded-md border border-zinc-200 px-2 text-sm"
            />
            <input
              type="number"
              min="30"
              value={windowDays}
              onChange={(event) => setWindowDays(event.target.value)}
              placeholder="统计天数"
              className="h-9 rounded-md border border-zinc-200 px-2 text-sm"
            />
            <input
              type="number"
              min="0"
              step="0.1"
              value={frequencyDays}
              onChange={(event) => setFrequencyDays(event.target.value)}
              placeholder="高频间隔"
              className="h-9 rounded-md border border-zinc-200 px-2 text-sm"
            />
            <input
              type="number"
              min="0"
              step="0.1"
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              placeholder="大单阈值"
              className="h-9 rounded-md border border-zinc-200 px-2 text-sm"
            />
            <input
              type="number"
              min="0"
              step="0.01"
              value={stability}
              onChange={(event) => setStability(event.target.value)}
              placeholder="稳定系数"
              className="h-9 rounded-md border border-zinc-200 px-2 text-sm"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <CommandButton
              disabled={busy || !ruleName.trim()}
              onClick={() => void createRule()}
            >
              <Plus className="size-4" />
              创建规则版本
            </CommandButton>
            {rules.slice(0, 5).map((rule) => (
              <span
                key={rule.id}
                className="inline-flex items-center gap-2 border-l border-zinc-200 pl-2 text-xs text-zinc-600"
              >
                v{rule.version_no} {rule.name}
                <StatusPill value={rule.status} />
                {rule.status === "draft" ? (
                  <IconButton
                    label={`激活规则 v${rule.version_no}`}
                    disabled={busy}
                    onClick={() => void activateRule(rule.id)}
                  >
                    <Check className="size-3.5" />
                  </IconButton>
                ) : null}
              </span>
            ))}
          </div>
        </section>
      ) : null}
      <div className="divide-y divide-zinc-200 border-y border-zinc-200">
        {rows.map((row) => (
          <div
            key={row.id}
            className="grid gap-3 py-4 lg:grid-cols-[180px_180px_minmax(220px,1fr)_auto]"
          >
            <div>
              <p className="text-sm font-medium text-zinc-900">
                {row.customer_code}
              </p>
              <p className="mt-1 text-xs text-zinc-400">
                {row.statistics_start} 至 {row.statistics_end}
              </p>
            </div>
            <div>
              <p className="text-sm text-zinc-800">{row.tag_name}</p>
              <p className="mt-1 text-xs text-zinc-400">
                置信度 {Math.round(Number(row.confidence) * 100)}%
              </p>
            </div>
            <div>
              <p className="break-words text-xs leading-5 text-zinc-500">
                订单 {String(row.metrics_json.order_count ?? "-")} 次 · 间隔{" "}
                {String(row.metrics_json.average_purchase_interval_days ?? "-")}{" "}
                天 · 单次{" "}
                {String(row.metrics_json.average_order_quantity ?? "-")}
              </p>
              {canSubmit ? (
                <input
                  value={notes[row.id] ?? ""}
                  onChange={(event) =>
                    setNotes((current) => ({
                      ...current,
                      [row.id]: event.target.value,
                    }))
                  }
                  placeholder="人工确认说明"
                  className="mt-2 h-9 w-full rounded-md border border-zinc-200 px-2 text-sm"
                />
              ) : null}
            </div>
            {canSubmit ? (
              <div className="flex gap-1">
                <IconButton
                  label="采纳推荐"
                  disabled={busy || !notes[row.id]?.trim()}
                  onClick={() => void decide(row, "accept")}
                >
                  <Check className="size-4" />
                </IconButton>
                <IconButton
                  label="拒绝推荐"
                  disabled={busy || !notes[row.id]?.trim()}
                  onClick={() => void decide(row, "reject")}
                >
                  <X className="size-4" />
                </IconButton>
              </div>
            ) : (
              <StatusPill value={row.status} />
            )}
          </div>
        ))}
        {rows.length === 0 ? (
          <div className="py-16 text-center text-sm text-zinc-400">
            暂无待确认推荐
          </div>
        ) : null}
      </div>
    </div>
  );
}

function CatalogVersionManager({
  activeCatalog,
  onChanged,
}: {
  activeCatalog: StructuredCustomerTag[];
  onChanged: () => void;
}) {
  const [versions, setVersions] = useState<CustomerTagCatalogVersion[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [definitions, setDefinitions] = useState<StructuredCustomerTag[]>([]);
  const [versionCode, setVersionCode] = useState("");
  const [versionName, setVersionName] = useState("");
  const [versionDescription, setVersionDescription] = useState("");
  const [stableCode, setStableCode] = useState("");
  const [tagName, setTagName] = useState("");
  const [categoryKey, setCategoryKey] =
    useState<CustomerTagCategoryKey>("classification");
  const [groupCode, setGroupCode] = useState("");
  const [groupName, setGroupName] = useState("");
  const [colorKey, setColorKey] = useState<CustomerTagColorKey>("blue");
  const [selectionRule, setSelectionRule] = useState<"single" | "multi">(
    "multi",
  );
  const [supportsTemporary, setSupportsTemporary] = useState(false);
  const [currentTagId, setCurrentTagId] = useState("");
  const [replacementTagId, setReplacementTagId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selectedVersion = versions.find(
    (item) => item.id === Number(selectedVersionId),
  );
  const currentTag = activeCatalog.find(
    (item) => item.id === Number(currentTagId),
  );
  const replacementOptions = definitions.filter(
    (item) => !currentTag || item.category_key === currentTag.category_key,
  );

  const loadVersions = async () => {
    const rows = await customerTagCatalogVersions();
    setVersions(rows);
    setSelectedVersionId(
      (current) =>
        current ||
        String(rows.find((item) => item.status === "draft")?.id ?? ""),
    );
  };
  useEffect(() => {
    void loadVersions().catch((reason) =>
      setError(reason instanceof Error ? reason.message : "目录版本加载失败"),
    );
  }, []);
  useEffect(() => {
    if (!selectedVersionId) {
      setDefinitions([]);
      return;
    }
    void customerTagCatalogVersionDefinitions(Number(selectedVersionId))
      .then(setDefinitions)
      .catch((reason) =>
        setError(reason instanceof Error ? reason.message : "版本定义加载失败"),
      );
  }, [selectedVersionId]);

  const createVersion = async () => {
    if (!versionCode.trim() || !versionName.trim()) return;
    setBusy(true);
    setError("");
    try {
      const row = await createCustomerTagCatalogVersion({
        version_code: versionCode.trim(),
        name: versionName.trim(),
        description: versionDescription.trim() || null,
      });
      setVersionCode("");
      setVersionName("");
      setVersionDescription("");
      await loadVersions();
      setSelectedVersionId(String(row.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "版本创建失败");
    } finally {
      setBusy(false);
    }
  };
  const addDefinition = async () => {
    if (
      !selectedVersion ||
      selectedVersion.status !== "draft" ||
      !stableCode.trim() ||
      !tagName.trim()
    )
      return;
    setBusy(true);
    setError("");
    try {
      await createCustomerTagCatalogDefinition(selectedVersion.id, {
        stable_code: stableCode.trim(),
        name: tagName.trim(),
        color_key: colorKey,
        category_key: categoryKey,
        category_name: CATEGORY_META[categoryKey].label,
        group_code: groupCode.trim() || null,
        group_name: groupName.trim() || null,
        selection_rule: selectionRule,
        attribute_types: supportsTemporary
          ? ["long_term", "temporary"]
          : ["long_term"],
      });
      setStableCode("");
      setTagName("");
      setGroupCode("");
      setGroupName("");
      setSupportsTemporary(false);
      setDefinitions(
        await customerTagCatalogVersionDefinitions(selectedVersion.id),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "定义创建失败");
    } finally {
      setBusy(false);
    }
  };
  const scheduleReplacement = async () => {
    if (!currentTagId || !replacementTagId) return;
    setBusy(true);
    setError("");
    try {
      await replaceCustomerTagCatalogDefinition(
        Number(currentTagId),
        Number(replacementTagId),
      );
      setCurrentTagId("");
      setReplacementTagId("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "替换设置失败");
    } finally {
      setBusy(false);
    }
  };
  const activate = async () => {
    if (
      !selectedVersion ||
      selectedVersion.status !== "draft" ||
      !window.confirm(`确认激活目录版本 ${selectedVersion.version_code}？`)
    )
      return;
    setBusy(true);
    setError("");
    try {
      await activateCustomerTagCatalogVersion(selectedVersion.id);
      await loadVersions();
      onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "版本激活失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mt-8 space-y-5 border-t border-zinc-200 pt-6">
      <SectionHeader
        icon={<History className="size-4" />}
        title="目录版本维护"
        action={
          selectedVersion?.status === "draft" ? (
            <CommandButton
              tone="primary"
              disabled={busy || definitions.length === 0}
              onClick={() => void activate()}
            >
              <Check className="size-4" />
              激活版本
            </CommandButton>
          ) : undefined
        }
      />
      {error ? (
        <div className="border-l-2 border-red-500 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      ) : null}
      <div className="grid gap-3 lg:grid-cols-[minmax(220px,0.7fr)_minmax(0,1.3fr)]">
        <div className="space-y-3">
          <select
            value={selectedVersionId}
            onChange={(event) => {
              setSelectedVersionId(event.target.value);
              setCurrentTagId("");
              setReplacementTagId("");
            }}
            className="h-10 w-full rounded-md border border-zinc-200 bg-white px-3 text-sm"
          >
            <option value="">选择目录版本</option>
            {versions.map((item) => (
              <option key={item.id} value={item.id}>
                {item.version_code} · {statusLabel[item.status] ?? item.status}
              </option>
            ))}
          </select>
          <div className="grid gap-2 border-y border-zinc-100 py-3">
            <input
              value={versionCode}
              onChange={(event) => setVersionCode(event.target.value)}
              placeholder="新版本编码"
              className="h-9 rounded-md border border-zinc-200 px-3 text-sm"
            />
            <input
              value={versionName}
              onChange={(event) => setVersionName(event.target.value)}
              placeholder="新版本名称"
              className="h-9 rounded-md border border-zinc-200 px-3 text-sm"
            />
            <input
              value={versionDescription}
              onChange={(event) => setVersionDescription(event.target.value)}
              placeholder="版本说明"
              className="h-9 rounded-md border border-zinc-200 px-3 text-sm"
            />
            <CommandButton
              disabled={busy || !versionCode.trim() || !versionName.trim()}
              onClick={() => void createVersion()}
            >
              <Plus className="size-4" />
              创建草稿版本
            </CommandButton>
          </div>
          {selectedVersion ? (
            <div className="text-xs leading-5 text-zinc-500">
              <p className="font-medium text-zinc-800">
                {selectedVersion.name}
              </p>
              <p>{selectedVersion.description ?? "未填写版本说明"}</p>
              <p>
                {formatDate(
                  selectedVersion.activated_at ?? selectedVersion.created_at,
                )}
              </p>
            </div>
          ) : null}
        </div>
        <div className="space-y-4">
          {selectedVersion?.status === "draft" ? (
            <>
              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                <input
                  value={stableCode}
                  onChange={(event) => setStableCode(event.target.value)}
                  placeholder="稳定编码"
                  className="h-9 rounded-md border border-zinc-200 px-2 text-sm"
                />
                <input
                  value={tagName}
                  onChange={(event) => setTagName(event.target.value)}
                  placeholder="标签名称"
                  className="h-9 rounded-md border border-zinc-200 px-2 text-sm"
                />
                <select
                  value={categoryKey}
                  onChange={(event) => {
                    const key = event.target.value as CustomerTagCategoryKey;
                    setCategoryKey(key);
                    setSelectionRule(
                      key === "classification" ? "single" : "multi",
                    );
                  }}
                  className="h-9 rounded-md border border-zinc-200 bg-white px-2 text-sm"
                >
                  {Object.entries(CATEGORY_META).map(([key, meta]) => (
                    <option key={key} value={key}>
                      {meta.label}
                    </option>
                  ))}
                </select>
                <select
                  value={colorKey}
                  onChange={(event) =>
                    setColorKey(event.target.value as CustomerTagColorKey)
                  }
                  className="h-9 rounded-md border border-zinc-200 bg-white px-2 text-sm"
                >
                  {[
                    "blue",
                    "green",
                    "cyan",
                    "yellow",
                    "red",
                    "purple",
                    "pink",
                    "gray",
                  ].map((key) => (
                    <option key={key} value={key}>
                      {key}
                    </option>
                  ))}
                </select>
                <input
                  value={groupCode}
                  onChange={(event) => setGroupCode(event.target.value)}
                  placeholder="分组编码"
                  className="h-9 rounded-md border border-zinc-200 px-2 text-sm"
                />
                <input
                  value={groupName}
                  onChange={(event) => setGroupName(event.target.value)}
                  placeholder="分组名称"
                  className="h-9 rounded-md border border-zinc-200 px-2 text-sm"
                />
                <label className="flex min-h-9 items-center gap-2 text-sm text-zinc-600">
                  <input
                    type="checkbox"
                    checked={supportsTemporary}
                    disabled={categoryKey !== "delivery_requirement"}
                    onChange={(event) =>
                      setSupportsTemporary(event.target.checked)
                    }
                  />
                  支持临时属性
                </label>
                <CommandButton
                  disabled={busy || !stableCode.trim() || !tagName.trim()}
                  onClick={() => void addDefinition()}
                >
                  <Plus className="size-4" />
                  新增定义
                </CommandButton>
              </div>
              <div className="grid gap-2 border-y border-zinc-100 py-3 md:grid-cols-[1fr_1fr_auto]">
                <select
                  value={currentTagId}
                  onChange={(event) => {
                    setCurrentTagId(event.target.value);
                    setReplacementTagId("");
                  }}
                  className="h-9 rounded-md border border-zinc-200 bg-white px-2 text-sm"
                >
                  <option value="">选择待替换的现行标签</option>
                  {activeCatalog.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.category_name} / {item.name}
                    </option>
                  ))}
                </select>
                <select
                  value={replacementTagId}
                  onChange={(event) => setReplacementTagId(event.target.value)}
                  className="h-9 rounded-md border border-zinc-200 bg-white px-2 text-sm"
                >
                  <option value="">选择新定义</option>
                  {replacementOptions.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
                <CommandButton
                  disabled={busy || !currentTagId || !replacementTagId}
                  onClick={() => void scheduleReplacement()}
                >
                  <RefreshCw className="size-4" />
                  设置替换
                </CommandButton>
              </div>
            </>
          ) : null}
          <div className="divide-y divide-zinc-100 border-y border-zinc-200">
            {definitions.map((item) => (
              <div
                key={item.id}
                className="grid gap-2 py-3 text-sm md:grid-cols-[150px_1fr_120px]"
              >
                <code className="text-xs text-zinc-500">
                  {item.stable_code}
                </code>
                <span className="text-zinc-800">
                  {item.category_name} / {item.group_name ?? "一级分类"} /{" "}
                  {item.name}
                </span>
                <StatusPill value={item.is_active ? "active" : "draft"} />
              </div>
            ))}
            {selectedVersionId && definitions.length === 0 ? (
              <div className="py-6 text-center text-sm text-zinc-400">
                此版本尚无定义
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}

export function CustomerTaggingWorkspace({
  permissions,
  initialCustomer = null,
  embedded = false,
}: {
  permissions: PermissionCode[];
  initialCustomer?: {
    customer_code: string;
    customer_name: string;
  } | null;
  embedded?: boolean;
}) {
  const canSubmit = hasPermission(permissions, "customer_tag.submit");
  const canReview = hasPermission(permissions, "customer_tag.review");
  const canManage = hasPermission(permissions, "customer_tag.catalog_manage");
  const canViewHistory = hasPermission(permissions, "customer_tag.history");
  const [view, setView] = useState<
    | "customers"
    | "profile"
    | "history"
    | "requests"
    | "recommendations"
    | "catalog"
    | "migration"
  >(initialCustomer ? "profile" : "customers");
  const [settings, setSettings] =
    useState<CustomerTagGovernanceSettings | null>(null);
  const [catalog, setCatalog] = useState<StructuredCustomerTag[]>([]);
  const [customer, setCustomer] = useState<{
    customer_code: string;
    customer_name: string;
  } | null>(initialCustomer);
  const [profile, setProfile] = useState<CustomerTagProfile | null>(null);
  const [editingAssignment, setEditingAssignment] =
    useState<CustomerTagAssignment | null>(null);
  const [history, setHistory] = useState<CustomerTagHistory | null>(null);
  const [requests, setRequests] = useState<CustomerTagChangeRequest[]>([]);
  const [requestComments, setRequestComments] = useState<
    Record<number, string>
  >({});
  const [supplementEvidence, setSupplementEvidence] = useState<
    Record<number, string>
  >({});
  const [legacy, setLegacy] = useState<LegacyMappingRow[]>([]);
  const [selectedLegacy, setSelectedLegacy] = useState<LegacyMappingRow | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadBase = async () => {
    const [nextSettings, nextCatalog] = await Promise.all([
      customerTagGovernanceSettings(),
      structuredCustomerTagCatalog(),
    ]);
    setSettings(nextSettings);
    setCatalog(nextCatalog);
  };
  useEffect(() => {
    void loadBase().catch((reason) =>
      setError(reason instanceof Error ? reason.message : "加载失败"),
    );
  }, []);

  const loadProfile = async (selected = customer) => {
    if (!selected) return;
    setLoading(true);
    setError("");
    try {
      setProfile(await structuredCustomerTagProfile(selected.customer_code));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!initialCustomer) return;
    let ignore = false;
    setCustomer(initialCustomer);
    setView("profile");
    setProfile(null);
    setHistory(null);
    setEditingAssignment(null);
    setLoading(true);
    setError("");
    structuredCustomerTagProfile(initialCustomer.customer_code)
      .then((nextProfile) => {
        if (!ignore) setProfile(nextProfile);
      })
      .catch((reason) => {
        if (!ignore)
          setError(reason instanceof Error ? reason.message : "标签画像加载失败");
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, [initialCustomer?.customer_code, initialCustomer?.customer_name]);

  const loadRequests = async () => {
    setLoading(true);
    try {
      setRequests(
        (await customerTagChangeRequests({ mine: !canReview })).items,
      );
    } finally {
      setLoading(false);
    }
  };

  const loadHistory = async (selected = customer) => {
    if (!selected || !canViewHistory) return;
    setLoading(true);
    setError("");
    try {
      setHistory(await customerTagHistory(selected.customer_code));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "历史加载失败");
    } finally {
      setLoading(false);
    }
  };

  const cancelAssignment = async (assignment: CustomerTagAssignment) => {
    if (!customer) return;
    setError("");
    try {
      await createCustomerTagChangeRequest({
        customer_code: customer.customer_code,
        reason: `申请取消标签：${assignment.tag_name}`,
        items: [
          {
            action: "cancel",
            assignment_id: assignment.id,
            tag_id: assignment.tag_id,
            evidence: `客户情况变化，申请取消：${assignment.tag_name}`,
            review_date: assignment.review_date,
            owner_user_id: assignment.owner_user_id,
            is_primary: assignment.is_primary,
            details_json: assignment.details_json ?? {},
          },
        ],
      });
      await loadRequests();
      setView("requests");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "提交失败");
    }
  };

  const decide = async (
    requestId: number,
    itemId: number,
    decision: "approved" | "need_supplement" | "rejected",
  ) => {
    await reviewCustomerTagChangeRequest(requestId, [
      {
        item_id: itemId,
        decision,
        comment: requestComments[itemId]?.trim() || undefined,
      },
    ]);
    setRequestComments((current) => ({ ...current, [itemId]: "" }));
    await loadRequests();
    if (customer) await loadProfile();
  };

  const supplement = async (
    request: CustomerTagChangeRequest,
    item: CustomerTagChangeRequest["items"][number],
  ) => {
    const evidence = (supplementEvidence[item.id] ?? item.evidence).trim();
    if (!evidence) return;
    await supplementCustomerTagChangeRequest(
      request.id,
      [
        {
          item_id: item.id,
          evidence,
          review_date: item.review_date,
          owner_user_id: item.owner_user_id,
          details_json: item.details_json ?? {},
        },
      ],
      requestComments[item.id]?.trim() || undefined,
    );
    setSupplementEvidence((current) => ({ ...current, [item.id]: "" }));
    setRequestComments((current) => ({ ...current, [item.id]: "" }));
    await loadRequests();
  };

  const updateSetting = async (
    key:
      | "tag_workflow_enabled"
      | "recommendation_enabled"
      | "fulfillment_enabled",
    value: boolean,
  ) => {
    const next = await updateCustomerTagGovernanceSettings({ [key]: value });
    setSettings(next);
  };

  const saveNumericSetting = async (
    key:
      | "default_reviewer_user_id"
      | "backup_reviewer_user_id"
      | "review_reminder_days",
    value: number | null,
  ) => {
    const payload: Partial<CustomerTagGovernanceSettings> =
      key === "review_reminder_days"
        ? { review_reminder_days: value ?? 7 }
        : key === "default_reviewer_user_id"
          ? { default_reviewer_user_id: value }
          : { backup_reviewer_user_id: value };
    const next = await updateCustomerTagGovernanceSettings(payload);
    setSettings(next);
  };

  const loadLegacy = async () =>
    setLegacy(await customerTagLegacyMappings({ status: "pending" }));

  const categoryCounts = useMemo(
    () =>
      Object.fromEntries(
        Object.keys(CATEGORY_META).map((key) => [
          key,
          catalog.filter((item) => item.category_key === key).length,
        ]),
      ),
    [catalog],
  );
  const catalogByGroup = useMemo(
    () =>
      catalog.reduce<Record<string, StructuredCustomerTag[]>>(
        (result, item) => {
          const key = item.group_name ?? "一级分类";
          (result[key] ??= []).push(item);
          return result;
        },
        {},
      ),
    [catalog],
  );
  const viewTabs: Array<[typeof view, string, typeof Tags]> = [
    ...(!embedded ? [["customers", "客户筛选", Search] as [typeof view, string, typeof Tags]] : []),
    ["profile", "标签画像", Tags],
  ];
  if (canViewHistory) viewTabs.push(["history", "变更历史", History]);
  if (canSubmit || canReview)
    viewTabs.push(["requests", canReview ? "标签审核" : "我的申请", ClipboardCheck]);
  if (canSubmit || canReview || canManage)
    viewTabs.push(["recommendations", "自动推荐", RefreshCw]);
  if (canManage) {
    viewTabs.push(
      ["catalog", "正式目录", Settings2],
      ["migration", "历史复核", History],
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-200 pb-4">
        <div>
          <p className="text-xs font-semibold uppercase text-zinc-500">
            Customer Tags
          </p>
          <h1 className={cx("mt-1 font-semibold text-zinc-950", embedded ? "text-lg" : "text-2xl")}>
            {embedded ? "标签管理" : "客户标签体系"}
          </h1>
          {embedded && customer ? (
            <p className="mt-1 text-xs text-zinc-500">
              {customer.customer_name} · {customer.customer_code}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <FeatureState settings={settings} feature="tag_workflow_enabled" />
          <FeatureState settings={settings} feature="recommendation_enabled" />
        </div>
      </div>
      <div className="flex flex-wrap gap-1 border-b border-zinc-200">
        {viewTabs.map(([key, label, Icon]) => (
          <button
            key={key}
            type="button"
            onClick={() => {
              setView(key);
              if (key === "requests") void loadRequests();
              if (key === "history") void loadHistory();
              if (key === "migration") void loadLegacy();
            }}
            className={cx(
              "flex min-h-10 items-center gap-2 border-b-2 px-3 text-sm",
              view === key
                ? "border-zinc-900 font-medium text-zinc-950"
                : "border-transparent text-zinc-500 hover:text-zinc-900",
            )}
          >
            <Icon className="size-4" />
            {label}
          </button>
        ))}
      </div>
      {error ? (
        <div className="flex items-start gap-2 border-l-2 border-red-500 bg-red-50 px-3 py-2 text-sm text-red-700">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          {error}
        </div>
      ) : null}

      {view === "customers" ? (
        <TaggedCustomerBrowser
          catalog={catalog}
          canExport={hasPermission(permissions, "customer_tag.export")}
          onOpen={(selected) => {
            setCustomer(selected);
            setProfile(null);
            setEditingAssignment(null);
            setView("profile");
            void loadProfile(selected);
          }}
        />
      ) : null}

      {view === "profile" ? (
        <div className={cx("grid gap-6", !embedded && "xl:grid-cols-[320px_minmax(0,1fr)]")}>
          {!embedded ? <aside className="border-r border-zinc-200 pr-5">
            <SectionHeader
              icon={<Search className="size-4" />}
              title="选择客户"
            />
            <div className="pt-4">
              <CustomerSearch
                onSelect={(selected) => {
                  setCustomer(selected);
                  setProfile(null);
                  setEditingAssignment(null);
                  void loadProfile(selected);
                }}
              />
            </div>
          </aside> : null}
          <main className="min-w-0">
            <SectionHeader
              icon={<Tags className="size-4" />}
              title={
                customer
                  ? `${customer.customer_name} · ${customer.customer_code}`
                  : "标签画像"
              }
              action={
                customer ? (
                  <IconButton
                    label="刷新标签画像"
                    onClick={() => void loadProfile()}
                    disabled={loading}
                  >
                    <RefreshCw
                      className={cx("size-4", loading && "animate-spin")}
                    />
                  </IconButton>
                ) : undefined
              }
            />
            {!customer ? (
              <div className="py-16 text-center text-sm text-zinc-400">
                请选择客户
              </div>
            ) : null}
            {profile ? (
              <div className="space-y-6 py-5">
                {Object.entries(CATEGORY_META).map(([key, meta]) => (
                  <section key={key}>
                    <div className="mb-2 flex items-center gap-2">
                      <span
                        className={cx(
                          "rounded border px-2 py-1 text-xs font-semibold",
                          meta.tone,
                        )}
                      >
                        {meta.label}
                      </span>
                      <span className="text-xs text-zinc-400">
                        {profile.by_category[key]?.length ?? 0}
                      </span>
                    </div>
                    <div className="border-y border-zinc-200">
                      {(profile.by_category[key] ?? []).length > 0 ? (
                        (profile.by_category[key] ?? []).map((assignment) => (
                          <AssignmentRow
                            key={assignment.id}
                            assignment={assignment}
                            canSubmit={canSubmit}
                            onEdit={setEditingAssignment}
                            onCancel={cancelAssignment}
                          />
                        ))
                      ) : (
                        <div className="py-5 text-sm text-zinc-400">
                          暂无有效标签
                        </div>
                      )}
                    </div>
                  </section>
                ))}
                {profile.legacy_tags.length > 0 ? (
                  <section>
                    <div className="mb-2 text-sm font-medium text-zinc-700">
                      历史标签
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {profile.legacy_tags.map((item) => (
                        <span
                          key={item.id}
                          className="rounded border border-zinc-200 bg-zinc-50 px-2 py-1 text-xs text-zinc-600"
                        >
                          {item.legacy_tag_name} ·{" "}
                          {statusLabel[item.status] ?? item.status}
                        </span>
                      ))}
                    </div>
                  </section>
                ) : null}
                {canSubmit && customer ? (
                  <TagApplicationForm
                    customer={customer}
                    catalog={catalog}
                    settings={settings}
                    assignment={editingAssignment}
                    onCancelEdit={() => setEditingAssignment(null)}
                    onSaved={() => {
                      void loadRequests();
                      setView("requests");
                    }}
                  />
                ) : null}
              </div>
            ) : null}
          </main>
        </div>
      ) : null}

      {view === "history" && canViewHistory ? (
        <div className={cx("grid gap-6", !embedded && "xl:grid-cols-[320px_minmax(0,1fr)]")}>
          {!embedded ? <aside className="border-r border-zinc-200 pr-5">
            <SectionHeader
              icon={<Search className="size-4" />}
              title="选择客户"
            />
            <div className="pt-4">
              <CustomerSearch
                onSelect={(selected) => {
                  setCustomer(selected);
                  setHistory(null);
                  void loadHistory(selected);
                }}
              />
            </div>
          </aside> : null}
          <main className="min-w-0">
            <SectionHeader
              icon={<History className="size-4" />}
              title={
                customer ? `${customer.customer_name} · 标签历史` : "标签历史"
              }
              action={
                customer ? (
                  <IconButton
                    label="刷新标签历史"
                    onClick={() => void loadHistory()}
                    disabled={loading}
                  >
                    <RefreshCw
                      className={cx("size-4", loading && "animate-spin")}
                    />
                  </IconButton>
                ) : undefined
              }
            />
            {!customer ? (
              <div className="py-16 text-center text-sm text-zinc-400">
                请选择客户
              </div>
            ) : null}
            {history ? <CustomerTagHistoryTimeline data={history} /> : null}
          </main>
        </div>
      ) : null}

      {view === "requests" ? (
        <div>
          <SectionHeader
            icon={<ClipboardCheck className="size-4" />}
            title={canReview ? "待我审核" : "我的申请"}
            action={
              <IconButton
                label="刷新申请"
                onClick={() => void loadRequests()}
                disabled={loading}
              >
                <RefreshCw
                  className={cx("size-4", loading && "animate-spin")}
                />
              </IconButton>
            }
          />
          <div className="divide-y divide-zinc-200">
            {requests.map((row) => (
              <section key={row.id} className="py-5">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <h3 className="font-medium text-zinc-900">
                      {row.customer_name ?? row.customer_code}
                    </h3>
                    <p className="mt-1 text-xs text-zinc-500">
                      {row.request_no} · {formatDate(row.submitted_at)}
                    </p>
                  </div>
                  <StatusPill value={row.status} />
                </div>
                <div className="mt-4 divide-y divide-zinc-100 border-y border-zinc-200">
                  {row.items.map((item) => (
                    <div
                      key={item.id}
                      className="grid gap-3 py-3 md:grid-cols-[1fr_1.4fr_auto]"
                    >
                      <div>
                        <span className="text-sm font-medium text-zinc-900">
                          {item.tag_name}
                        </span>
                        <p className="mt-1 text-xs text-zinc-500">
                          {item.action} · {item.group_code ?? "一级分类"}
                        </p>
                      </div>
                      <div className="space-y-2">
                        {item.status === "need_supplement" && !canReview ? (
                          <textarea
                            value={supplementEvidence[item.id] ?? item.evidence}
                            onChange={(event) =>
                              setSupplementEvidence((current) => ({
                                ...current,
                                [item.id]: event.target.value,
                              }))
                            }
                            rows={2}
                            className="w-full resize-y rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-sm text-amber-900"
                          />
                        ) : (
                          <p className="text-sm text-zinc-600">
                            {item.evidence}
                          </p>
                        )}
                        {item.review_comment ? (
                          <p className="border-l-2 border-amber-300 pl-2 text-xs text-amber-700">
                            审批意见：{item.review_comment}
                          </p>
                        ) : null}
                        {(canReview &&
                          ["pending", "need_supplement"].includes(
                            item.status,
                          )) ||
                        (!canReview && item.status === "need_supplement") ? (
                          <input
                            value={requestComments[item.id] ?? ""}
                            onChange={(event) =>
                              setRequestComments((current) => ({
                                ...current,
                                [item.id]: event.target.value,
                              }))
                            }
                            placeholder={
                              canReview
                                ? "审批意见（退回或拒绝时必填）"
                                : "补充说明（可选）"
                            }
                            className="h-9 w-full rounded-md border border-zinc-200 px-2 text-sm"
                          />
                        ) : null}
                      </div>
                      <div className="flex gap-1">
                        {canReview &&
                        ["pending", "need_supplement"].includes(item.status) ? (
                          <>
                            <IconButton
                              label="通过"
                              onClick={() =>
                                void decide(row.id, item.id, "approved")
                              }
                            >
                              <Check className="size-4" />
                            </IconButton>
                            <IconButton
                              label="退回补充"
                              disabled={!requestComments[item.id]?.trim()}
                              onClick={() =>
                                void decide(row.id, item.id, "need_supplement")
                              }
                            >
                              <RefreshCw className="size-4" />
                            </IconButton>
                            <IconButton
                              label="拒绝"
                              disabled={!requestComments[item.id]?.trim()}
                              onClick={() =>
                                void decide(row.id, item.id, "rejected")
                              }
                            >
                              <X className="size-4" />
                            </IconButton>
                          </>
                        ) : !canReview &&
                          canSubmit &&
                          item.status === "need_supplement" ? (
                          <CommandButton
                            disabled={
                              !(
                                supplementEvidence[item.id] ?? item.evidence
                              ).trim()
                            }
                            onClick={() => void supplement(row, item)}
                          >
                            <Send className="size-4" />
                            补充并提交
                          </CommandButton>
                        ) : (
                          <StatusPill value={item.status} />
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            ))}
            {requests.length === 0 ? (
              <div className="py-16 text-center text-sm text-zinc-400">
                暂无申请
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {view === "recommendations" ? (
        <CustomerTagRecommendationWorkspace
          canManage={canManage}
          canSubmit={canSubmit}
          enabled={Boolean(settings?.recommendation_enabled)}
        />
      ) : null}

      {view === "catalog" && canManage ? (
        <div className="space-y-6">
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
            <main>
              <SectionHeader
                icon={<Tags className="size-4" />}
                title="当前正式目录"
              />
              <div className="grid gap-px bg-zinc-200 sm:grid-cols-2 lg:grid-cols-4">
                {Object.entries(CATEGORY_META).map(([key, meta]) => (
                  <div key={key} className="bg-white p-4">
                    <span
                      className={cx(
                        "inline-flex rounded border px-2 py-1 text-xs font-semibold",
                        meta.tone,
                      )}
                    >
                      {meta.label}
                    </span>
                    <div className="mt-4 text-2xl font-semibold text-zinc-950">
                      {categoryCounts[key] ?? 0}
                    </div>
                    <div className="mt-1 text-xs text-zinc-400">固定标签</div>
                  </div>
                ))}
              </div>
              <div className="mt-6 divide-y divide-zinc-100 border-y border-zinc-200">
                {Object.entries(catalogByGroup).map(([group, items]) => (
                  <div
                    key={group}
                    className="grid gap-3 py-4 md:grid-cols-[220px_1fr]"
                  >
                    <div className="text-sm font-medium text-zinc-800">
                      {group}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {items.map((item) => (
                        <span
                          key={item.id}
                          className="rounded border border-zinc-200 px-2 py-1 text-xs text-zinc-600"
                        >
                          {item.name}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </main>
            <aside className="border-l border-zinc-200 pl-5">
              <SectionHeader
                icon={<Settings2 className="size-4" />}
                title="启用控制"
              />
              <div className="divide-y divide-zinc-100">
                {[
                  ["tag_workflow_enabled", "标签申请与审核"],
                  ["recommendation_enabled", "采购特征推荐"],
                  ["fulfillment_enabled", "订单配送联动"],
                ].map(([key, label]) => (
                  <label
                    key={key}
                    className="flex min-h-14 items-center justify-between gap-3 text-sm text-zinc-700"
                  >
                    <span>{label}</span>
                    <input
                      type="checkbox"
                      checked={Boolean(
                        settings?.[key as keyof CustomerTagGovernanceSettings],
                      )}
                      onChange={(event) =>
                        void updateSetting(
                          key as
                            | "tag_workflow_enabled"
                            | "recommendation_enabled"
                            | "fulfillment_enabled",
                          event.target.checked,
                        )
                      }
                    />
                  </label>
                ))}
              </div>
              <div className="mt-4 space-y-3 border-t border-zinc-200 pt-4">
                <label className="block space-y-1 text-sm">
                  <span className="text-zinc-600">默认审核人 ID</span>
                  <input
                    inputMode="numeric"
                    value={settings?.default_reviewer_user_id ?? ""}
                    onChange={(event) =>
                      setSettings((current) =>
                        current
                          ? {
                              ...current,
                              default_reviewer_user_id: event.target.value
                                ? Number(event.target.value)
                                : null,
                            }
                          : current,
                      )
                    }
                    onBlur={() =>
                      void saveNumericSetting(
                        "default_reviewer_user_id",
                        settings?.default_reviewer_user_id ?? null,
                      )
                    }
                    className="h-9 w-full rounded-md border border-zinc-200 px-2"
                  />
                </label>
                <label className="block space-y-1 text-sm">
                  <span className="text-zinc-600">备用审核人 ID</span>
                  <input
                    inputMode="numeric"
                    value={settings?.backup_reviewer_user_id ?? ""}
                    onChange={(event) =>
                      setSettings((current) =>
                        current
                          ? {
                              ...current,
                              backup_reviewer_user_id: event.target.value
                                ? Number(event.target.value)
                                : null,
                            }
                          : current,
                      )
                    }
                    onBlur={() =>
                      void saveNumericSetting(
                        "backup_reviewer_user_id",
                        settings?.backup_reviewer_user_id ?? null,
                      )
                    }
                    className="h-9 w-full rounded-md border border-zinc-200 px-2"
                  />
                </label>
                <label className="block space-y-1 text-sm">
                  <span className="text-zinc-600">提前提醒天数</span>
                  <input
                    type="number"
                    min="0"
                    max="90"
                    value={settings?.review_reminder_days ?? 7}
                    onChange={(event) =>
                      setSettings((current) =>
                        current
                          ? {
                              ...current,
                              review_reminder_days: Number(event.target.value),
                            }
                          : current,
                      )
                    }
                    onBlur={() =>
                      void saveNumericSetting(
                        "review_reminder_days",
                        settings?.review_reminder_days ?? 7,
                      )
                    }
                    className="h-9 w-full rounded-md border border-zinc-200 px-2"
                  />
                </label>
              </div>
            </aside>
          </div>
          <CatalogVersionManager
            activeCatalog={catalog}
            onChanged={() => void loadBase()}
          />
        </div>
      ) : null}

      {view === "migration" && canManage ? (
        <div
          className={cx(
            "grid gap-6",
            selectedLegacy && "xl:grid-cols-[minmax(0,1fr)_420px]",
          )}
        >
          <main>
            <SectionHeader
              icon={<History className="size-4" />}
              title="历史标签待复核"
              action={
                <IconButton
                  label="刷新待复核"
                  onClick={() => void loadLegacy()}
                >
                  <RefreshCw className="size-4" />
                </IconButton>
              }
            />
            <div className="divide-y divide-zinc-200">
              {legacy.map((item) => (
                <div
                  key={item.id}
                  className="grid gap-3 py-4 md:grid-cols-[1fr_1fr_auto]"
                >
                  <div>
                    <span className="text-sm font-medium text-zinc-900">
                      {item.legacy_tag_name}
                    </span>
                    <p className="mt-1 text-xs text-zinc-500">
                      {item.customer_code} · 置信度{" "}
                      {item.confidence == null
                        ? "未匹配"
                        : `${Math.round(item.confidence * 100)}%`}
                    </p>
                  </div>
                  <div className="text-sm text-zinc-600">
                    <p>{item.target_tag_name ?? "无候选"}</p>
                    <p className="mt-1 text-xs text-zinc-400">
                      {item.rationale}
                    </p>
                  </div>
                  <div className="flex gap-1">
                    <IconButton
                      label="结构化复核"
                      onClick={() => setSelectedLegacy(item)}
                    >
                      <Send className="size-4" />
                    </IconButton>
                    <IconButton
                      label="标记未匹配"
                      onClick={async () => {
                        await reviewCustomerTagLegacyMapping(item.id, {
                          decision: "unmatched",
                          evidence: "暂无合适正式标签",
                        });
                        if (selectedLegacy?.id === item.id)
                          setSelectedLegacy(null);
                        await loadLegacy();
                      }}
                    >
                      <X className="size-4" />
                    </IconButton>
                  </div>
                </div>
              ))}
              {legacy.length === 0 ? (
                <div className="py-16 text-center text-sm text-zinc-400">
                  暂无待复核标签
                </div>
              ) : null}
            </div>
          </main>
          {selectedLegacy ? (
            <LegacyMappingReviewForm
              mapping={selectedLegacy}
              catalog={catalog}
              onClose={() => setSelectedLegacy(null)}
              onSaved={() => {
                setSelectedLegacy(null);
                void loadLegacy();
              }}
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function OrderLinesEditor({
  lines,
  onChange,
}: {
  lines: SalesOrderLinePayload[];
  onChange: (lines: SalesOrderLinePayload[]) => void;
}) {
  const update = (index: number, patch: Partial<SalesOrderLinePayload>) =>
    onChange(
      lines.map((line, lineIndex) =>
        lineIndex === index ? { ...line, ...patch } : line,
      ),
    );
  return (
    <div className="divide-y divide-zinc-100 border-y border-zinc-200">
      {lines.map((line, index) => (
        <div
          key={index}
          className="grid gap-2 py-3 md:grid-cols-[130px_minmax(180px,1fr)_120px_90px_auto]"
        >
          <input
            value={line.product_code ?? ""}
            onChange={(event) =>
              update(index, { product_code: event.target.value })
            }
            placeholder="商品编号"
            className="h-9 rounded-md border border-zinc-200 px-2 text-sm"
          />
          <input
            value={line.product_name}
            onChange={(event) =>
              update(index, { product_name: event.target.value })
            }
            placeholder="商品名称"
            className="h-9 rounded-md border border-zinc-200 px-2 text-sm"
          />
          <input
            type="number"
            min="0.0001"
            step="0.0001"
            value={line.quantity || ""}
            onChange={(event) =>
              update(index, { quantity: Number(event.target.value) })
            }
            placeholder="数量"
            className="h-9 rounded-md border border-zinc-200 px-2 text-sm"
          />
          <input
            value={line.unit ?? ""}
            onChange={(event) => update(index, { unit: event.target.value })}
            placeholder="单位"
            className="h-9 rounded-md border border-zinc-200 px-2 text-sm"
          />
          <IconButton
            label="删除明细"
            disabled={lines.length === 1}
            onClick={() =>
              onChange(lines.filter((_, lineIndex) => lineIndex !== index))
            }
          >
            <X className="size-4" />
          </IconButton>
        </div>
      ))}
    </div>
  );
}

export function SalesOrdersWorkspace({
  permissions,
}: {
  permissions: PermissionCode[];
}) {
  const canCreate = hasPermission(permissions, "sales_order.create");
  const canConfirm = hasPermission(permissions, "sales_order.confirm");
  const canImport = hasPermission(permissions, "sales_order.import");
  const canCancel =
    hasPermission(permissions, "sales_order.edit") || canConfirm;
  const [settings, setSettings] =
    useState<CustomerTagGovernanceSettings | null>(null);
  const [deliveryCatalog, setDeliveryCatalog] = useState<
    StructuredCustomerTag[]
  >([]);
  const [rows, setRows] = useState<SalesOrderRow[]>([]);
  const [selected, setSelected] = useState<SalesOrderRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] =
    useState<SalesOrderImportResult | null>(null);
  const [cancelReason, setCancelReason] = useState("");
  const [cancelling, setCancelling] = useState(false);
  const [customerCode, setCustomerCode] = useState("");
  const [externalNo, setExternalNo] = useState("");
  const [address, setAddress] = useState("");
  const [plannedAt, setPlannedAt] = useState("");
  const [temporaryTagId, setTemporaryTagId] = useState("");
  const [temporaryNote, setTemporaryNote] = useState("");
  const [temporaryRequirements, setTemporaryRequirements] = useState<
    Array<{
      tag_id: number;
      tag_name: string;
      group_code?: string | null;
      details: { note: string };
    }>
  >([]);
  const [lines, setLines] = useState<SalesOrderLinePayload[]>([
    { product_name: "", quantity: 0 },
  ]);
  const [error, setError] = useState("");
  const load = async () => {
    const [nextSettings, page, tags] = await Promise.all([
      customerTagGovernanceSettings(),
      salesOrders(),
      structuredCustomerTagCatalog({ categoryKey: "delivery_requirement" }),
    ]);
    setSettings(nextSettings);
    setRows(page.items);
    setDeliveryCatalog(
      tags.filter((tag) =>
        (
          tag.applicability_json?.attribute_types as unknown[] | undefined
        )?.includes("temporary"),
      ),
    );
  };
  useEffect(() => {
    void load().catch((reason) =>
      setError(reason instanceof Error ? reason.message : "加载失败"),
    );
  }, []);
  const create = async () => {
    try {
      await createSalesOrder({
        external_order_no: externalNo || undefined,
        customer_code: customerCode,
        delivery_address: address || null,
        planned_delivery_at: plannedAt
          ? new Date(plannedAt).toISOString()
          : null,
        temporary_requirements: temporaryRequirements,
        lines,
      });
      setCreating(false);
      setCustomerCode("");
      setExternalNo("");
      setAddress("");
      setPlannedAt("");
      setTemporaryTagId("");
      setTemporaryNote("");
      setTemporaryRequirements([]);
      setLines([{ product_name: "", quantity: 0 }]);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
    }
  };
  const confirm = async (order: SalesOrderRow) => {
    try {
      const next = await confirmSalesOrder(order.id);
      setSelected(next);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "确认失败");
    }
  };
  const refresh = async (order: SalesOrderRow) => {
    try {
      const next = await refreshSalesOrderRequirements(order.id);
      setSelected(next);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "同步失败");
    }
  };
  const importWorkbook = async () => {
    if (!importFile) return;
    setImporting(true);
    setError("");
    try {
      const result = await importSalesOrders(importFile);
      setImportResult(result);
      setImportFile(null);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "导入失败");
    } finally {
      setImporting(false);
    }
  };
  const cancel = async (order: SalesOrderRow) => {
    if (!cancelReason.trim()) return;
    setCancelling(true);
    setError("");
    try {
      const next = await cancelSalesOrder(order.id, cancelReason.trim());
      setSelected(next);
      setCancelReason("");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "取消失败");
    } finally {
      setCancelling(false);
    }
  };
  const addTemporaryRequirement = () => {
    const tag = deliveryCatalog.find(
      (item) => item.id === Number(temporaryTagId),
    );
    if (!tag || temporaryRequirements.some((item) => item.tag_id === tag.id))
      return;
    setTemporaryRequirements([
      ...temporaryRequirements,
      {
        tag_id: tag.id,
        tag_name: tag.name,
        group_code: tag.group_code,
        details: { note: temporaryNote.trim() },
      },
    ]);
    setTemporaryTagId("");
    setTemporaryNote("");
  };
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-200 pb-4">
        <div>
          <p className="text-xs font-semibold uppercase text-zinc-500">
            Sales Orders
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-zinc-950">
            销售订单
          </h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <FeatureState settings={settings} feature="fulfillment_enabled" />
          {canImport ? (
            <CommandButton
              disabled={!settings?.fulfillment_enabled}
              onClick={() => setImportOpen((value) => !value)}
            >
              <FileSpreadsheet className="size-4" />
              Excel 导入
            </CommandButton>
          ) : null}
          {canCreate ? (
            <CommandButton
              tone="primary"
              disabled={!settings?.fulfillment_enabled}
              onClick={() => setCreating((value) => !value)}
            >
              <Plus className="size-4" />
              新建订单
            </CommandButton>
          ) : null}
        </div>
      </div>
      {error ? (
        <div className="border-l-2 border-red-500 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      ) : null}
      {importOpen && canImport ? (
        <section className="space-y-4 border-y border-zinc-200 py-5">
          <SectionHeader
            icon={<Upload className="size-4" />}
            title="订单 Excel 导入"
            action={
              <IconButton label="关闭导入" onClick={() => setImportOpen(false)}>
                <X className="size-4" />
              </IconButton>
            }
          />
          <div className="flex flex-wrap items-center gap-3">
            <input
              type="file"
              accept=".xlsx,.xls"
              onChange={(event) => {
                setImportFile(event.target.files?.[0] ?? null);
                setImportResult(null);
              }}
              className="min-w-0 flex-1 rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm file:mr-3 file:rounded file:border-0 file:bg-zinc-100 file:px-3 file:py-1 file:text-sm file:font-medium"
            />
            <CommandButton
              tone="primary"
              disabled={!importFile || importing}
              onClick={() => void importWorkbook()}
            >
              <Upload className="size-4" />
              {importing ? "导入中" : "开始导入"}
            </CommandButton>
          </div>
          {importResult ? (
            <div className="space-y-3 border-l-2 border-zinc-300 bg-zinc-50 px-3 py-3 text-sm text-zinc-700">
              <p>
                成功 {importResult.imported_orders} 个订单 /{" "}
                {importResult.imported_lines} 条明细
                {importResult.errors.length
                  ? `，失败 ${importResult.errors.length} 个订单`
                  : ""}
              </p>
              {importResult.errors.length ? (
                <div className="divide-y divide-red-100 text-xs text-red-700">
                  {importResult.errors.map((item, index) => (
                    <p
                      key={`${item.external_order_no ?? "row"}-${index}`}
                      className="py-1"
                    >
                      {item.external_order_no ?? "未识别订单"}：{item.message}
                    </p>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}
      {creating ? (
        <section className="space-y-4 border-y border-zinc-200 py-5">
          <SectionHeader
            icon={<Plus className="size-4" />}
            title="新建订单"
            action={
              <IconButton label="关闭" onClick={() => setCreating(false)}>
                <X className="size-4" />
              </IconButton>
            }
          />
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
            <input
              value={customerCode}
              onChange={(event) => setCustomerCode(event.target.value)}
              placeholder="客户编号"
              className="h-10 rounded-md border border-zinc-200 px-3 text-sm"
            />
            <input
              value={externalNo}
              onChange={(event) => setExternalNo(event.target.value)}
              placeholder="外部订单号"
              className="h-10 rounded-md border border-zinc-200 px-3 text-sm"
            />
            <input
              type="datetime-local"
              value={plannedAt}
              onChange={(event) => setPlannedAt(event.target.value)}
              className="h-10 rounded-md border border-zinc-200 px-3 text-sm"
            />
            <input
              value={address}
              onChange={(event) => setAddress(event.target.value)}
              placeholder="配送地址"
              className="h-10 rounded-md border border-zinc-200 px-3 text-sm"
            />
          </div>
          <div className="space-y-2 border-y border-zinc-100 py-3">
            <div className="grid gap-2 md:grid-cols-[minmax(180px,1fr)_minmax(180px,1fr)_auto]">
              <select
                value={temporaryTagId}
                onChange={(event) => setTemporaryTagId(event.target.value)}
                className="h-10 rounded-md border border-zinc-200 bg-white px-3 text-sm"
              >
                <option value="">临时配送要求</option>
                {deliveryCatalog.map((tag) => (
                  <option key={tag.id} value={tag.id}>
                    {tag.name}
                  </option>
                ))}
              </select>
              <input
                value={temporaryNote}
                onChange={(event) => setTemporaryNote(event.target.value)}
                placeholder="本单临时要求说明"
                className="h-10 rounded-md border border-zinc-200 px-3 text-sm"
              />
              <IconButton
                label="添加临时配送要求"
                disabled={!temporaryTagId}
                onClick={addTemporaryRequirement}
              >
                <Plus className="size-4" />
              </IconButton>
            </div>
            <div className="flex flex-wrap gap-2">
              {temporaryRequirements.map((item) => (
                <span
                  key={item.tag_id}
                  className="inline-flex items-center gap-1 rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-800"
                >
                  {item.tag_name}
                  <button
                    type="button"
                    aria-label={`移除${item.tag_name}`}
                    onClick={() =>
                      setTemporaryRequirements(
                        temporaryRequirements.filter(
                          (value) => value.tag_id !== item.tag_id,
                        ),
                      )
                    }
                  >
                    <X className="size-3" />
                  </button>
                </span>
              ))}
            </div>
          </div>
          <OrderLinesEditor lines={lines} onChange={setLines} />
          <div className="flex justify-between">
            <CommandButton
              onClick={() =>
                setLines([...lines, { product_name: "", quantity: 0 }])
              }
            >
              <Plus className="size-4" />
              增加明细
            </CommandButton>
            <CommandButton
              tone="primary"
              disabled={
                !customerCode ||
                lines.some((line) => !line.product_name || line.quantity <= 0)
              }
              onClick={() => void create()}
            >
              <Check className="size-4" />
              保存草稿
            </CommandButton>
          </div>
        </section>
      ) : null}
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        <main>
          <SectionHeader
            icon={<PackageCheck className="size-4" />}
            title={`订单列表 · ${rows.length}`}
          />
          <div className="divide-y divide-zinc-200">
            {rows.map((row) => (
              <button
                key={row.id}
                type="button"
                onClick={() => setSelected(row)}
                className={cx(
                  "grid w-full gap-2 py-4 text-left md:grid-cols-[1fr_1fr_140px_auto]",
                  selected?.id === row.id && "bg-zinc-50 px-2",
                )}
              >
                <div>
                  <span className="text-sm font-medium text-zinc-900">
                    {row.order_no}
                  </span>
                  <p className="mt-1 text-xs text-zinc-500">
                    {row.external_order_no ?? "无外部单号"}
                  </p>
                </div>
                <div>
                  <span className="text-sm text-zinc-800">
                    {row.customer_name_snapshot}
                  </span>
                  <p className="mt-1 text-xs text-zinc-500">
                    {row.customer_code}
                  </p>
                </div>
                <div className="text-xs text-zinc-500">
                  {formatDate(row.planned_delivery_at)}
                </div>
                <StatusPill value={row.status} />
              </button>
            ))}
          </div>
        </main>
        <aside className="border-l border-zinc-200 pl-5">
          <SectionHeader
            icon={<ClipboardCheck className="size-4" />}
            title="订单明细"
          />
          {selected ? (
            <div className="space-y-5 py-4">
              <div>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-zinc-900">
                    {selected.order_no}
                  </span>
                  <StatusPill value={selected.status} />
                </div>
                <p className="mt-2 text-sm text-zinc-600">
                  {selected.delivery_address ?? "未填写配送地址"}
                </p>
              </div>
              <div>
                <h3 className="mb-2 text-xs font-semibold text-zinc-500">
                  商品明细
                </h3>
                <div className="divide-y divide-zinc-100 border-y border-zinc-200">
                  {selected.lines.map((line) => (
                    <div
                      key={line.id}
                      className="flex justify-between gap-3 py-2 text-sm"
                    >
                      <span className="min-w-0 truncate">
                        {line.product_name}
                      </span>
                      <span className="shrink-0 text-zinc-500">
                        {line.quantity} {line.unit}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <h3 className="mb-2 text-xs font-semibold text-zinc-500">
                  配送要求快照 v{selected.requirement_snapshot_version}
                </h3>
                <div className="flex flex-wrap gap-2">
                  {selected.requirements.length ? (
                    selected.requirements.map((item) => (
                      <span
                        key={item.id}
                        className="rounded border border-zinc-200 px-2 py-1 text-xs text-zinc-600"
                      >
                        {item.tag_name} ·{" "}
                        {item.source_type === "temporary" ? "临时" : "长期"}
                      </span>
                    ))
                  ) : (
                    <span className="text-sm text-zinc-400">尚未生成</span>
                  )}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {canConfirm && selected.status === "draft" ? (
                  <CommandButton
                    tone="primary"
                    onClick={() => void confirm(selected)}
                  >
                    <Check className="size-4" />
                    确认订单
                  </CommandButton>
                ) : null}
                {canConfirm &&
                ["confirmed", "delivering"].includes(selected.status) ? (
                  <CommandButton onClick={() => void refresh(selected)}>
                    <RefreshCw className="size-4" />
                    重新同步要求
                  </CommandButton>
                ) : null}
              </div>
              {canCancel && ["draft", "confirmed"].includes(selected.status) ? (
                <div className="space-y-2 border-t border-zinc-100 pt-4">
                  <textarea
                    value={cancelReason}
                    onChange={(event) => setCancelReason(event.target.value)}
                    placeholder="订单取消原因"
                    rows={2}
                    className="w-full resize-y rounded-md border border-zinc-200 px-3 py-2 text-sm"
                  />
                  <CommandButton
                    tone="danger"
                    disabled={!cancelReason.trim() || cancelling}
                    onClick={() => void cancel(selected)}
                  >
                    <Ban className="size-4" />
                    {cancelling ? "取消中" : "取消订单"}
                  </CommandButton>
                </div>
              ) : null}
              {selected.requirement_diff &&
              selected.requirement_diff.added.length +
                selected.requirement_diff.removed.length +
                selected.requirement_diff.changed.length >
                0 ? (
                <div className="border-l-2 border-amber-400 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  新增 {selected.requirement_diff.added.length} · 移除{" "}
                  {selected.requirement_diff.removed.length} · 变化{" "}
                  {selected.requirement_diff.changed.length}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="py-16 text-center text-sm text-zinc-400">
              请选择订单
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

export function DeliveryWorkspace({
  permissions,
}: {
  permissions: PermissionCode[];
}) {
  const canManage = hasPermission(permissions, "delivery.manage");
  const [rows, setRows] = useState<DeliveryTaskRow[]>([]);
  const [selected, setSelected] = useState<DeliveryTaskRow | null>(null);
  const [signer, setSigner] = useState("");
  const [exception, setException] = useState("");
  const [attachmentFile, setAttachmentFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [downloadingId, setDownloadingId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const load = async () => setRows((await deliveryTasks()).items);
  useEffect(() => {
    void load().catch((reason) =>
      setError(reason instanceof Error ? reason.message : "加载失败"),
    );
  }, []);
  const transition = async (
    toStatus: string,
    eventType: string,
    note?: string,
  ) => {
    if (!selected) return;
    try {
      const next = await updateDeliveryTask(selected.id, {
        event_type: eventType,
        to_status: toStatus,
        note,
        signed_by: toStatus === "delivered" ? signer : undefined,
      });
      setSelected(next);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "更新失败");
    }
  };
  const uploadAttachment = async () => {
    if (!selected || !attachmentFile) return;
    setUploading(true);
    setError("");
    try {
      const attachment = await uploadDeliveryAttachment(
        selected.id,
        attachmentFile,
      );
      setSelected({
        ...selected,
        attachments: [attachment, ...selected.attachments],
      });
      setAttachmentFile(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "附件上传失败");
    } finally {
      setUploading(false);
    }
  };
  const downloadAttachment = async (attachmentId: number, fileName: string) => {
    if (!selected) return;
    setDownloadingId(attachmentId);
    setError("");
    try {
      saveBlob(
        await downloadDeliveryAttachment(selected.id, attachmentId),
        fileName,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "附件下载失败");
    } finally {
      setDownloadingId(null);
    }
  };
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-200 pb-4">
        <div>
          <p className="text-xs font-semibold uppercase text-zinc-500">
            Delivery
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-zinc-950">
            配送执行
          </h1>
        </div>
        <IconButton label="刷新配送任务" onClick={() => void load()}>
          <RefreshCw className="size-4" />
        </IconButton>
      </div>
      {error ? (
        <div className="border-l-2 border-red-500 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      ) : null}
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        <main>
          <SectionHeader
            icon={<Truck className="size-4" />}
            title={`配送任务 · ${rows.length}`}
          />
          <div className="divide-y divide-zinc-200">
            {rows.map((row) => (
              <button
                key={row.id}
                type="button"
                onClick={() => setSelected(row)}
                className={cx(
                  "grid w-full gap-2 py-4 text-left md:grid-cols-[1fr_1fr_140px_auto]",
                  selected?.id === row.id && "bg-zinc-50 px-2",
                )}
              >
                <div>
                  <span className="text-sm font-medium text-zinc-900">
                    {row.delivery_no}
                  </span>
                  <p className="mt-1 text-xs text-zinc-500">{row.order_no}</p>
                </div>
                <div>
                  <span className="text-sm text-zinc-800">
                    {row.customer_name}
                  </span>
                  <p className="mt-1 text-xs text-zinc-500">
                    {row.delivery_address}
                  </p>
                </div>
                <div className="text-xs text-zinc-500">
                  {formatDate(row.planned_at)}
                </div>
                <StatusPill value={row.status} />
              </button>
            ))}
          </div>
        </main>
        <aside className="border-l border-zinc-200 pl-5">
          <SectionHeader
            icon={<ClipboardCheck className="size-4" />}
            title="执行明细"
          />
          {selected ? (
            <div className="space-y-5 py-4">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-zinc-900">
                  {selected.delivery_no}
                </span>
                <StatusPill value={selected.status} />
              </div>
              <div>
                <h3 className="mb-2 text-xs font-semibold text-zinc-500">
                  配送要求
                </h3>
                <div className="space-y-2 border-y border-zinc-200 py-3">
                  {(selected.requirements_json ?? []).map((raw, index) => (
                    <div key={index} className="text-sm text-zinc-700">
                      {String(raw.tag_name ?? raw["tag_name"] ?? "配送要求")}
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <h3 className="mb-2 text-xs font-semibold text-zinc-500">
                  交付附件 · {selected.attachments.length}
                </h3>
                <div className="divide-y divide-zinc-100 border-y border-zinc-200">
                  {selected.attachments.map((attachment) => (
                    <div
                      key={attachment.id}
                      className="flex items-center justify-between gap-3 py-2"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm text-zinc-800">
                          {attachment.file_name}
                        </p>
                        <p className="mt-1 text-xs text-zinc-400">
                          {formatBytes(attachment.size_bytes)} ·{" "}
                          {formatDate(attachment.created_at)}
                        </p>
                      </div>
                      <IconButton
                        label={`下载${attachment.file_name}`}
                        disabled={downloadingId === attachment.id}
                        onClick={() =>
                          void downloadAttachment(
                            attachment.id,
                            attachment.file_name,
                          )
                        }
                      >
                        <Download className="size-4" />
                      </IconButton>
                    </div>
                  ))}
                  {selected.attachments.length === 0 ? (
                    <div className="py-4 text-sm text-zinc-400">暂无附件</div>
                  ) : null}
                </div>
                {canManage ? (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <input
                      type="file"
                      onChange={(event) =>
                        setAttachmentFile(event.target.files?.[0] ?? null)
                      }
                      className="min-w-0 flex-1 rounded-md border border-zinc-200 bg-white px-2 py-1.5 text-xs file:mr-2 file:rounded file:border-0 file:bg-zinc-100 file:px-2 file:py-1"
                    />
                    <IconButton
                      label="上传交付附件"
                      disabled={!attachmentFile || uploading}
                      onClick={() => void uploadAttachment()}
                    >
                      <Paperclip className="size-4" />
                    </IconButton>
                  </div>
                ) : null}
              </div>
              {canManage &&
              !["delivered", "cancelled"].includes(selected.status) ? (
                <div className="space-y-3">
                  <div className="flex flex-wrap gap-2">
                    {selected.status === "pending" ? (
                      <CommandButton
                        onClick={() => void transition("planned", "plan")}
                      >
                        <ClipboardCheck className="size-4" />
                        安排
                      </CommandButton>
                    ) : null}
                    {["pending", "planned", "exception"].includes(
                      selected.status,
                    ) ? (
                      <CommandButton
                        tone="primary"
                        onClick={() =>
                          void transition("delivering", "dispatch")
                        }
                      >
                        <Truck className="size-4" />
                        开始配送
                      </CommandButton>
                    ) : null}
                  </div>
                  {selected.status === "delivering" ? (
                    <div className="space-y-2">
                      <input
                        value={signer}
                        onChange={(event) => setSigner(event.target.value)}
                        placeholder="签收人"
                        className="h-10 w-full rounded-md border border-zinc-200 px-3 text-sm"
                      />
                      <CommandButton
                        tone="primary"
                        disabled={!signer.trim()}
                        onClick={() => void transition("delivered", "sign")}
                      >
                        <Check className="size-4" />
                        确认签收
                      </CommandButton>
                    </div>
                  ) : null}
                  <div className="space-y-2 border-t border-zinc-100 pt-3">
                    <textarea
                      value={exception}
                      onChange={(event) => setException(event.target.value)}
                      placeholder="异常说明"
                      rows={2}
                      className="w-full rounded-md border border-zinc-200 px-3 py-2 text-sm"
                    />
                    <CommandButton
                      tone="danger"
                      disabled={!exception.trim()}
                      onClick={() =>
                        void transition("exception", "exception", exception)
                      }
                    >
                      <AlertTriangle className="size-4" />
                      记录异常
                    </CommandButton>
                    {["pending", "planned"].includes(selected.status) ? (
                      <CommandButton
                        tone="danger"
                        disabled={!exception.trim()}
                        onClick={() =>
                          void transition("cancelled", "cancel", exception)
                        }
                      >
                        <Ban className="size-4" />
                        取消配送
                      </CommandButton>
                    ) : null}
                  </div>
                </div>
              ) : null}
              {selected.exception_note ? (
                <div className="border-l-2 border-red-400 bg-red-50 px-3 py-2 text-sm text-red-700">
                  {selected.exception_note}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="py-16 text-center text-sm text-zinc-400">
              请选择配送任务
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
