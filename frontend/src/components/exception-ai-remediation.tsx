import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowLeft, CheckCircle2, FileText, LoaderCircle, Paperclip, PlayCircle, Trash2, Upload, XCircle } from "lucide-react";
import {
  cancelRemediation,
  confirmRemediation,
  deleteRemediationAttachment,
  generateRemediationPlan,
  remediationReferences,
  saveRemediationAnswers,
  uploadRemediationAttachment,
  type RemediationFormField,
  type RemediationWorkflow,
} from "../api/ai-remediation";
import { SafeMarkdown } from "./safe-markdown";

type Props = {
  initial: RemediationWorkflow;
  onChange: (workflow: RemediationWorkflow) => void;
  onBack: () => void;
};

const actionLabels: Record<string, string> = {
  rebuild_inventory_flow: "重建库存流转",
  rerun_inventory_check: "重跑库存核验",
  rebuild_receivable_checks: "重建应收核验",
  rebuild_master_link_issues: "重建主数据关联检查",
  revalidate_import_batch: "重新校验导入批次",
};

function planMarkdown(workflow: RemediationWorkflow): string {
  const plan = workflow.plan;
  if (!plan) return "";
  const list = (title: string, values: string[]) => values.length ? `\n### ${title}\n${values.map((item) => `- ${item}`).join("\n")}` : "";
  return `## 修复方案\n${plan.summary}${list("已确认事实", plan.confirmed_facts)}${list("合理推断", plan.assumptions)}${list("执行步骤", plan.steps)}\n### 预期影响\n${plan.expected_impact}${list("验证方法", plan.verification_steps)}\n### 回滚方式\n${plan.rollback}${list("风险与注意事项", plan.risks)}${list("仍需补充的信息", plan.missing_information)}`;
}

function FieldInput({ field, value, options, disabled, onChange }: { field: RemediationFormField; value: unknown; options: Array<{ value: string; label: string }>; disabled: boolean; onChange: (value: unknown) => void }) {
  const common = "remediation-input";
  if (field.field_type === "long_text") return <textarea className={common} rows={4} maxLength={field.max_length ?? 2000} value={String(value ?? "")} disabled={disabled} onChange={(event) => onChange(event.target.value)} />;
  if (field.field_type === "boolean") return <label className="remediation-toggle"><input type="checkbox" checked={Boolean(value)} disabled={disabled} onChange={(event) => onChange(event.target.checked)} /><span>{value ? "是" : "否"}</span></label>;
  if (field.field_type === "single_select" || field.field_type === "business_reference") {
    const rows = field.field_type === "single_select" ? field.options : options;
    return <select className={common} value={String(value ?? "")} disabled={disabled} onChange={(event) => onChange(event.target.value)}><option value="">请选择</option>{rows.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>;
  }
  if (field.field_type === "multi_select") {
    const selected = Array.isArray(value) ? value.map(String) : [];
    return <div className="remediation-options">{field.options.map((item) => <label key={item.value}><input type="checkbox" checked={selected.includes(item.value)} disabled={disabled} onChange={(event) => onChange(event.target.checked ? [...selected, item.value] : selected.filter((entry) => entry !== item.value))} />{item.label}</label>)}</div>;
  }
  if (field.field_type === "file") return null;
  const type = field.field_type === "number" ? "number" : field.field_type === "date" ? "date" : field.field_type === "datetime" ? "datetime-local" : "text";
  return <input className={common} type={type} value={value === null || value === undefined ? "" : String(value)} min={field.min_value ?? undefined} max={field.max_value ?? undefined} maxLength={field.max_length ?? (field.field_type === "short_text" ? 500 : undefined)} disabled={disabled} onChange={(event) => onChange(type === "number" ? (event.target.value === "" ? null : Number(event.target.value)) : event.target.value)} />;
}

export function ExceptionAiRemediation({ initial, onChange, onBack }: Props) {
  const [workflow, setWorkflow] = useState(initial);
  const [answers, setAnswers] = useState<Record<string, unknown>>(initial.answers ?? {});
  const [references, setReferences] = useState<Record<string, Array<{ value: string; label: string }>>>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const schema = workflow.form_schema;
  const plan = workflow.plan;
  const step = workflow.status === "completed" || workflow.status === "failed" ? 4 : plan ? 2 : 1;
  const planText = useMemo(() => planMarkdown(workflow), [workflow]);

  const replaceWorkflow = (next: RemediationWorkflow) => {
    setWorkflow(next);
    setAnswers(next.answers ?? {});
    onChange(next);
  };

  useEffect(() => {
    const referenceTypes = Array.from(new Set((schema?.fields ?? []).map((field) => field.reference_type).filter(Boolean))) as string[];
    referenceTypes.forEach((type) => {
      void remediationReferences(workflow.workflow_no, type).then((rows) => setReferences((current) => ({ ...current, [type]: rows }))).catch(() => setReferences((current) => ({ ...current, [type]: [] })));
    });
  }, [schema, workflow.workflow_no]);

  const run = async (label: string, action: () => Promise<RemediationWorkflow>) => {
    setBusy(label);
    setError("");
    try {
      replaceWorkflow(await action());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : `${label}失败，请稍后重试`);
    } finally {
      setBusy("");
    }
  };

  const createPlan = async () => {
    setBusy("正在生成修复方案");
    setError("");
    try {
      const saved = await saveRemediationAnswers(workflow, answers);
      replaceWorkflow(saved);
      replaceWorkflow(await generateRemediationPlan(saved));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "修复方案生成失败，请稍后重试");
    } finally {
      setBusy("");
    }
  };

  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    await run("正在安全扫描并解析附件", () => uploadRemediationAttachment(workflow.workflow_no, file));
  };

  const resultMode = String(workflow.result.mode ?? "");
  if (workflow.status === "cancelled" || (workflow.status === "failed" && !plan)) {
    return <section className="exception-remediation" data-testid="exception-ai-remediation"><div className="remediation-toolbar"><button type="button" onClick={onBack}><ArrowLeft className="h-4 w-4" />返回对话</button><span>案件 {workflow.case_no} · 证据 {workflow.evidence_version}</span></div><div className="remediation-result"><XCircle className="h-10 w-10 text-muted-foreground" /><h3>{workflow.status === "cancelled" ? "修复流程已取消" : "修复流程未完成"}</h3><p>{workflow.status === "cancelled" ? "本次补充信息和修复方案流程已停止。" : `错误代码：${workflow.error_code ?? "remediation_failed"}`}</p><button type="button" className="remediation-primary" onClick={onBack}><ArrowLeft className="h-4 w-4" />返回对话</button></div></section>;
  }
  return <section className="exception-remediation" data-testid="exception-ai-remediation">
    <div className="remediation-toolbar"><button type="button" onClick={onBack} disabled={Boolean(busy)}><ArrowLeft className="h-4 w-4" />返回对话</button><span>案件 {workflow.case_no} · 证据 {workflow.evidence_version}</span></div>
    <div className="remediation-steps" aria-label="受控修复流程">{["补充信息", "修复方案", "执行进度", "执行结果"].map((label, index) => <div key={label} className={step >= index + 1 ? "is-active" : ""}><span>{index + 1}</span>{label}</div>)}</div>

    {workflow.status === "stale" ? <div className="remediation-blocked"><AlertTriangle className="h-5 w-5" /><div><strong>案件证据已更新</strong><p>旧方案已失效，请返回对话重新分析后再生成修复方案。</p></div></div> : null}

    {!plan && workflow.status !== "stale" ? <div className="remediation-body"><div className="remediation-intro"><h3>{schema?.title ?? "补充异常修复信息"}</h3><p>{schema?.reason ?? "正在准备安全表单"}</p></div><div className="remediation-form">{(schema?.fields ?? []).map((field) => <label key={field.field_id} className="remediation-field"><span>{field.label}{field.required ? <b>*</b> : null}</span>{field.description ? <small>{field.description}</small> : null}{field.field_type === "file" ? <div className="remediation-upload"><label><Upload className="h-4 w-4" />选择附件<input type="file" hidden accept=".jpg,.jpeg,.png,.webp,.pdf,.xlsx,.xls,.csv" disabled={Boolean(busy) || workflow.attachments.length >= 5} onChange={(event) => void upload(event)} /></label><span>单文件 10MB，最多 5 个；上传后先安全扫描</span></div> : <FieldInput field={field} value={answers[field.field_id]} options={references[field.reference_type ?? ""] ?? []} disabled={Boolean(busy)} onChange={(value) => setAnswers((current) => ({ ...current, [field.field_id]: value }))} />}</label>)}{workflow.attachments.length ? <div className="remediation-files">{workflow.attachments.map((file) => <div key={file.attachment_no}><Paperclip className="h-4 w-4" /><span><strong>{file.original_name}</strong><small>{(file.size_bytes / 1024 / 1024).toFixed(2)}MB · 已扫描并解析</small></span><button type="button" title="删除附件" disabled={Boolean(busy)} onClick={() => void run("正在删除附件", () => deleteRemediationAttachment(workflow.workflow_no, file.attachment_no))}><Trash2 className="h-4 w-4" /></button></div>)}</div> : null}</div><button className="remediation-primary" type="button" disabled={Boolean(busy)} onClick={() => void createPlan()}>{busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}{busy || "生成修复方案"}</button></div> : null}

    {plan && workflow.status !== "completed" && workflow.status !== "failed" ? <div className="remediation-body"><SafeMarkdown content={planText} /><div className="remediation-impact"><strong>确定性执行信息</strong><dl><div><dt>动作</dt><dd>{plan.action_candidate.action_type ? actionLabels[plan.action_candidate.action_type] ?? plan.action_candidate.action_type : "无匹配动作，将转人工工单"}</dd></div><div><dt>沙箱</dt><dd>{plan.sandbox_candidate ? workflow.sandbox.status === "passed" ? "隔离验证通过" : "隔离验证未通过，将转人工工单" : "不需要代码验证"}</dd></div><div><dt>执行资格</dt><dd>{workflow.can_execute ? "可提交受控动作" : "服务端将在确认时复核，必要时转人工工单"}</dd></div></dl></div><label className="remediation-confirm"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />我已核对修复范围、影响和回滚方式</label><button className="remediation-primary" type="button" disabled={!confirmed || Boolean(busy)} onClick={() => void run("正在预演、执行并复检", () => confirmRemediation(workflow))}>{busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}{busy || "确认并执行"}</button></div> : null}

    {(workflow.status === "completed" || workflow.status === "failed") ? <div className="remediation-result">{workflow.status === "completed" ? <CheckCircle2 className="h-10 w-10 text-emerald-600" /> : <XCircle className="h-10 w-10 text-red-600" />}<h3>{resultMode === "work_item" ? "已转人工修复工单" : workflow.status === "completed" ? "受控修复已完成" : "受控修复未完成"}</h3><p>{resultMode === "work_item" ? `工单 ${String(workflow.result.work_item_no ?? "已创建")}，原因：${String(workflow.result.reason ?? "需要人工处理")}` : `动作状态：${String(workflow.result.status ?? workflow.error_code ?? workflow.status)}`}</p>{workflow.result.verification ? <pre>{JSON.stringify(workflow.result.verification, null, 2)}</pre> : null}<button type="button" className="remediation-primary" onClick={onBack}><ArrowLeft className="h-4 w-4" />返回对话</button></div> : null}

    {workflow.status !== "completed" && workflow.status !== "cancelled" && !busy ? <button className="remediation-cancel" type="button" onClick={() => void run("正在取消", () => cancelRemediation(workflow))}>取消当前流程</button> : null}
    {error ? <p className="remediation-error" role="alert">{error}</p> : null}
  </section>;
}
