import { FormEvent, KeyboardEvent, lazy, Suspense, useEffect, useRef, useState } from "react";
import { Bot, Check, ClipboardList, Copy, ExternalLink, History, LoaderCircle, Menu, Plus, RotateCcw, Send, ShieldCheck, Sparkles, Square, Trash2, X } from "lucide-react";
import {
  aiChatConversations,
  aiChatMessages,
  cancelAiChatRun,
  deleteAiChatConversation,
  streamAiChat,
  type AiCaseContextMeta,
  type AiChatArtifact,
  type AiChatContext,
  type AiChatConversation,
  type AiChatMessage,
  type AiChatStreamEvent,
} from "../api/ai-chat";
import { createRemediation, type RemediationWorkflow } from "../api/ai-remediation";

const SafeMarkdown = lazy(() =>
  import("./safe-markdown").then((module) => ({ default: module.SafeMarkdown })),
);
const ExceptionAiRemediation = lazy(() =>
  import("./exception-ai-remediation").then((module) => ({ default: module.ExceptionAiRemediation })),
);

export type ExceptionAssistantLaunch = {
  id: string;
  context: AiChatContext;
  contextMeta: AiCaseContextMeta;
  operation: "exception.case_analysis";
  message: string;
};

type Props = {
  open: boolean;
  context: AiChatContext;
  contextLabel: string;
  launch: ExceptionAssistantLaunch | null;
  onLaunchConsumed: (id: string) => void;
  onSendingChange: (sending: boolean) => void;
  onClearContext: () => void;
  onClose: () => void;
  onNavigatePath: (path: string) => void;
  onOpenCase: (caseNo: string, focusActions?: boolean) => void;
};

const suggestions = [
  "汇总当前高风险异常",
  "今天应该优先处理哪些案件",
  "分析已选案件的共同原因",
  "给出当前案件的核查步骤",
];

const analysisStages = ["正在读取案件背景", "正在整理证据", "正在分析原因", "正在生成解决方案"];
const severityLabels: Record<string, string> = { critical: "严重", high: "高", warning: "警告" };
const statusLabels: Record<string, string> = { open: "待处理", action_required: "待执行", processing: "处理中", blocked: "证据不足", resolved: "已解决", ignored: "已忽略" };

function temporaryMessage(
  role: "user" | "assistant",
  content: string,
  status = "completed",
  contextMeta: Partial<AiCaseContextMeta> = {},
): AiChatMessage {
  return {
    message_no: `local-${crypto.randomUUID()}`,
    sequence_no: Date.now(),
    role,
    content,
    status,
    source_refs: [],
    context_meta: contextMeta,
    artifacts: [],
    created_at: new Date().toISOString(),
  };
}

function latestCaseMeta(messages: AiChatMessage[]): Partial<AiCaseContextMeta> {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].context_meta?.case_no) return messages[index].context_meta;
  }
  return {};
}

export function ExceptionAiChat({
  open,
  context,
  contextLabel,
  launch,
  onLaunchConsumed,
  onSendingChange,
  onClearContext,
  onClose,
  onNavigatePath,
  onOpenCase,
}: Props) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<AiChatMessage[]>([]);
  const [conversations, setConversations] = useState<AiChatConversation[]>([]);
  const [conversationNo, setConversationNo] = useState<string | null>(null);
  const [runNo, setRunNo] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [followTail, setFollowTail] = useState(true);
  const [analysisStage, setAnalysisStage] = useState(0);
  const [caseMeta, setCaseMeta] = useState<Partial<AiCaseContextMeta>>({});
  const [copiedMessageNo, setCopiedMessageNo] = useState("");
  const [remediation, setRemediation] = useState<RemediationWorkflow | null>(null);
  const [remediationLoading, setRemediationLoading] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const lastLaunchRef = useRef("");

  const refreshConversations = async () => {
    try {
      const rows = await aiChatConversations();
      setConversations(rows);
      return rows;
    } catch {
      setConversations([]);
      return [];
    }
  };

  useEffect(() => {
    onSendingChange(sending);
  }, [onSendingChange, sending]);

  useEffect(() => {
    if (!open) return;
    setError("");
    void refreshConversations();
    window.setTimeout(() => textareaRef.current?.focus(), 120);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  useEffect(() => {
    if (followTail) scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: sending ? "auto" : "smooth" });
  }, [messages, followTail, sending]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const newConversation = () => {
    abortRef.current?.abort();
    setConversationNo(null);
    setMessages([]);
    setRunNo(null);
    setCaseMeta({});
    setAnalysisStage(0);
    setError("");
    setHistoryOpen(false);
    setRemediation(null);
  };

  const openConversation = async (row: AiChatConversation) => {
    if (sending) return;
    setError("");
    try {
      const rows = await aiChatMessages(row.conversation_no);
      setMessages(rows);
      setCaseMeta(latestCaseMeta(rows));
      setConversationNo(row.conversation_no);
      setHistoryOpen(false);
      setRemediation(null);
      setFollowTail(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "会话加载失败");
    }
  };

  const removeConversation = async () => {
    if (!conversationNo || sending || !window.confirm("确认删除当前 AI 会话？")) return;
    try {
      await deleteAiChatConversation(conversationNo);
      newConversation();
      await refreshConversations();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "会话删除失败");
    }
  };

  const handleStreamEvent = (event: AiChatStreamEvent) => {
    if (event.event === "run_started") {
      setRunNo(String(event.data.run_no ?? ""));
      setConversationNo(String(event.data.conversation_no ?? "") || null);
      setAnalysisStage(1);
      return;
    }
    if (event.event === "context_ready") {
      setAnalysisStage(2);
      if (event.data.case_no) {
        setCaseMeta({
          case_no: String(event.data.case_no),
          title: String(event.data.title ?? ""),
          severity: String(event.data.severity ?? ""),
          status: String(event.data.status ?? ""),
          evidence_version: String(event.data.evidence_version ?? ""),
          evidence_truncated: Boolean(event.data.evidence_truncated),
        });
      }
      return;
    }
    if (event.event === "message_started") {
      setAnalysisStage(3);
      return;
    }
    if (event.event === "delta") {
      setAnalysisStage(4);
      const text = String(event.data.text ?? "");
      setMessages((current) => {
        const next = [...current];
        const last = next[next.length - 1];
        if (last?.role === "assistant" && last.status === "streaming") next[next.length - 1] = { ...last, content: last.content + text };
        return next;
      });
      return;
    }
    if (event.event === "artifact") {
      const artifact = event.data.artifact as AiChatArtifact | undefined;
      if (!artifact) return;
      setMessages((current) => current.map((item, index) => index === current.length - 1 ? { ...item, artifacts: [...item.artifacts, artifact] } : item));
      return;
    }
    if (event.event === "message_completed") {
      const completed = event.data.message as AiChatMessage | undefined;
      setMessages((current) => completed ? [...current.slice(0, -1), completed] : current);
      setAnalysisStage(5);
      return;
    }
    if (event.event === "cancelled") {
      setMessages((current) => current.map((item, index) => index === current.length - 1 ? { ...item, status: "cancelled" } : item));
      return;
    }
    if (event.event === "error") {
      setError(String(event.data.message ?? "AI 回复生成失败，请稍后重试"));
      setMessages((current) => current.map((item, index) => index === current.length - 1 ? { ...item, status: "failed" } : item));
    }
  };

  const sendMessage = async (
    content: string,
    operation = "assistant.message",
    requestContext = context,
    explicitConversationNo: string | null = conversationNo,
    contextMeta: Partial<AiCaseContextMeta> = caseMeta,
    clientRequestId: string = crypto.randomUUID(),
  ) => {
    const normalized = content.trim();
    if (!normalized || sending) return;
    setError("");
    setInput("");
    setFollowTail(true);
    setAnalysisStage(operation === "exception.case_analysis" ? 1 : 0);
    setMessages((current) => [
      ...current,
      temporaryMessage("user", normalized, "completed", contextMeta),
      temporaryMessage("assistant", "", "streaming", contextMeta),
    ]);
    setSending(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamAiChat(
        {
          client_request_id: clientRequestId,
          conversation_no: explicitConversationNo,
          message: normalized,
          channel: "exception_center_web",
          operation,
          context: requestContext,
        },
        handleStreamEvent,
        controller.signal,
      );
      await refreshConversations();
    } catch (reason) {
      if (controller.signal.aborted) {
        setMessages((current) => current.map((item, index) => index === current.length - 1 ? { ...item, status: "cancelled" } : item));
      } else {
        setError(reason instanceof Error ? reason.message : "AI 回复生成失败，请稍后重试");
        setMessages((current) => current.map((item, index) => index === current.length - 1 ? { ...item, status: "failed" } : item));
      }
    } finally {
      setSending(false);
      abortRef.current = null;
      setRunNo(null);
    }
  };

  useEffect(() => {
    if (!open || !launch || sending || lastLaunchRef.current === launch.id) return;
    lastLaunchRef.current = launch.id;
    onLaunchConsumed(launch.id);
    setCaseMeta(launch.contextMeta);
    setHistoryOpen(false);
    setError("");
    void (async () => {
      const conversationRows = await refreshConversations();
      const existing = conversationRows.find((row) => row.context_type === "exception_case" && row.context_id === launch.contextMeta.case_no);
      let existingMessages: AiChatMessage[] = [];
      if (existing) {
        try {
          existingMessages = await aiChatMessages(existing.conversation_no);
        } catch {
          existingMessages = [];
        }
      }
      setMessages(existingMessages);
      setConversationNo(existing?.conversation_no ?? null);
      await sendMessage(
        launch.message,
        launch.operation,
        launch.context,
        existing?.conversation_no ?? null,
        launch.contextMeta,
        launch.id,
      );
    })();
  }, [launch, open, sending]);

  const send = async (event?: FormEvent, suggested?: string) => {
    event?.preventDefault();
    await sendMessage(suggested ?? input);
  };

  const stop = async () => {
    abortRef.current?.abort();
    if (runNo) void cancelAiChatRun(runNo).catch(() => undefined);
  };

  const reanalyze = (message: AiChatMessage) => {
    const meta = message.context_meta;
    if (!meta?.case_no || sending) return;
    void sendMessage(
      "分析该异常发生的原因，并给出可验证的解决方案",
      "exception.case_analysis",
      { scope: "case", filters: {}, case_nos: [meta.case_no] },
      conversationNo,
      meta,
    );
  };

  const copyMessage = async (message: AiChatMessage) => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopiedMessageNo(message.message_no);
      window.setTimeout(() => setCopiedMessageNo(""), 1400);
    } catch {
      setError("复制失败，请手动选择回答内容");
    }
  };

  const startRemediation = async (message: AiChatMessage) => {
    if (sending || remediationLoading) return;
    setRemediationLoading(message.message_no);
    setError("");
    try {
      setRemediation(await createRemediation(message.message_no));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "补充信息表单生成失败，请稍后重试");
    } finally {
      setRemediationLoading("");
    }
  };

  if (!open) return null;
  const caseConversations = conversations.filter((row) => row.context_type === "exception_case");
  const generalConversations = conversations.filter((row) => row.context_type !== "exception_case");
  const progress = analysisStage >= 5 ? 100 : [0, 20, 45, 70, 90][analysisStage] ?? 0;
  let renderedEvidenceVersion = "";

  return (
    <div className="exception-ai-overlay" data-testid="exception-ai-chat-overlay">
      <button className="exception-ai-scrim" type="button" aria-label="关闭异常处理助手" onClick={onClose} />
      <aside className="exception-ai-chat" role="dialog" aria-modal="true" aria-label="异常处理助手">
        <header className="exception-ai-chat-header">
          <div className="flex min-w-0 items-center gap-3">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-primary-soft text-primary"><Sparkles className="h-4 w-4" /></span>
            <div className="min-w-0"><h2 className="m-0 truncate text-base font-black text-foreground">异常处理助手</h2><p className="m-0 mt-0.5 text-xs font-bold text-muted-foreground">GLM-5.2 · 分析与受控处置</p></div>
          </div>
          <div className="flex items-center gap-1">
            <button className="exception-ai-icon-button" type="button" title="会话历史" aria-label="会话历史" onClick={() => setHistoryOpen((value) => !value)}><Menu className="h-4 w-4" /></button>
            <button className="exception-ai-icon-button" type="button" title="新建会话" aria-label="新建会话" onClick={newConversation}><Plus className="h-4 w-4" /></button>
            <button className="exception-ai-icon-button" type="button" title="关闭" aria-label="关闭" onClick={onClose}><X className="h-4 w-4" /></button>
          </div>
        </header>

        {historyOpen ? <section className="exception-ai-history" data-testid="exception-ai-history"><div className="flex items-center justify-between"><strong className="text-sm font-black text-foreground">会话历史</strong><History className="h-4 w-4 text-muted-foreground" /></div><div className="mt-3 min-h-0 flex-1 overflow-y-auto">{[{ label: "案件分析", rows: caseConversations }, { label: "普通问答", rows: generalConversations }].map((group) => <div key={group.label} className="mb-4"><p className="m-0 mb-1 px-2 text-xs font-black text-muted-foreground">{group.label}</p><div className="grid gap-1">{group.rows.map((row) => <button key={row.conversation_no} type="button" className={`exception-ai-history-row ${conversationNo === row.conversation_no ? "is-active" : ""}`} onClick={() => void openConversation(row)}><strong>{row.title}</strong><span>{row.context_id ? `${row.context_id} · 证据 ${row.evidence_version || "未标记"}` : row.last_message || "暂无回复"}</span></button>)}{group.rows.length === 0 ? <span className="px-2 py-2 text-xs font-bold text-muted-foreground">暂无记录</span> : null}</div></div>)}</div></section> : null}

        {caseMeta.case_no ? <div className="exception-ai-case-context" data-testid="exception-ai-case-context"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><strong className="font-mono text-xs text-primary">{caseMeta.case_no}</strong><span className={`exception-ai-case-badge is-${caseMeta.severity || "warning"}`}>{severityLabels[caseMeta.severity || ""] || "未分级"}</span><span className="exception-ai-case-badge">{statusLabels[caseMeta.status || ""] || "未标记"}</span></div><p className="m-0 mt-1 truncate text-sm font-black text-foreground">{caseMeta.title}</p><span className="mt-1 block text-xs font-bold text-muted-foreground">证据版本 {caseMeta.evidence_version || "未标记"}{caseMeta.evidence_truncated ? " · 上下文已裁剪" : ""}</span></div></div> : <div className="exception-ai-context"><button type="button" onClick={onClearContext} title="移除案件上下文">{contextLabel}<X className="h-3.5 w-3.5" /></button></div>}

        {sending && analysisStage > 0 ? <div className="exception-ai-progress" aria-label="AI 单案分析进度" data-testid="exception-ai-progress"><div className="flex items-center justify-between gap-3"><strong>{analysisStages[Math.min(Math.max(analysisStage - 1, 0), 3)]}</strong><span>{progress}%</span></div><div className="exception-ai-progress-track"><span style={{ width: `${progress}%` }} /></div></div> : null}

        {remediation ? <Suspense fallback={<div className="grid flex-1 place-items-center text-sm font-black text-muted-foreground">正在打开受控修复流程</div>}><ExceptionAiRemediation initial={remediation} onChange={setRemediation} onBack={() => setRemediation(null)} /></Suspense> : <div ref={scrollRef} className="exception-ai-messages" onScroll={(event) => { const node = event.currentTarget; setFollowTail(node.scrollHeight - node.scrollTop - node.clientHeight < 80); }}>
          {messages.length === 0 ? <div className="exception-ai-welcome"><span className="grid h-12 w-12 place-items-center rounded-lg border border-border bg-white text-primary shadow-sm"><Bot className="h-6 w-6" /></span><div><h3 className="m-0 text-xl font-black text-foreground">今天需要先处理什么？</h3><p className="m-0 mt-2 text-sm font-bold leading-6 text-muted-foreground">我会基于当前账号有权查看的异常、证据与业务上下文给出建议，不会直接修改业务数据。</p></div><div className="grid w-full gap-2">{suggestions.map((item) => <button key={item} className="exception-ai-suggestion" type="button" onClick={() => void send(undefined, item)}>{item}<Send className="h-3.5 w-3.5" /></button>)}</div></div> : messages.map((message) => {
            const version = message.context_meta?.evidence_version || "";
            const showVersionDivider = Boolean(version && renderedEvidenceVersion && version !== renderedEvidenceVersion);
            if (version) renderedEvidenceVersion = version;
            const artifact = message.artifacts?.find((item) => item.type === "exception_case_analysis");
            const artifactCaseNo = artifact?.case?.case_no || message.context_meta?.case_no;
            return <div key={message.message_no}>{showVersionDivider ? <div className="exception-ai-evidence-divider"><span>证据已更新 · {version}</span></div> : null}<article className={`exception-ai-message is-${message.role}`}>{message.content ? (message.role === "assistant" ? <Suspense fallback={<div className="whitespace-pre-wrap text-sm font-bold leading-7">{message.content}</div>}><SafeMarkdown content={message.content} /></Suspense> : <div className="whitespace-pre-wrap text-sm font-bold leading-7">{message.content}</div>) : (message.status === "streaming" ? <span className="exception-ai-thinking">正在分析当前上下文</span> : "未生成内容")}{message.status === "failed" ? <span className="mt-1 block text-xs font-black text-red-600">生成失败</span> : message.status === "cancelled" ? <span className="mt-1 block text-xs font-black text-muted-foreground">已停止生成</span> : null}{message.role === "assistant" && message.status === "completed" && message.content ? <div className="exception-ai-result-actions">{artifactCaseNo && artifact?.remediation_enabled ? <button type="button" className="is-primary" disabled={Boolean(remediationLoading)} onClick={() => void startRemediation(message)}>{remediationLoading === message.message_no ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <ClipboardList className="h-3.5 w-3.5" />}补充信息</button> : null}<button type="button" onClick={() => void copyMessage(message)}>{copiedMessageNo === message.message_no ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}{copiedMessageNo === message.message_no ? "已复制" : "复制结果"}</button>{artifactCaseNo ? <button type="button" onClick={() => reanalyze(message)} disabled={sending}><RotateCcw className="h-3.5 w-3.5" />重新分析</button> : null}{artifact?.action_path ? <button type="button" onClick={() => { onClose(); onNavigatePath(artifact.action_path as string); }}><ExternalLink className="h-3.5 w-3.5" />查看原始记录</button> : null}{artifactCaseNo ? <button type="button" onClick={() => { onClose(); onOpenCase(artifactCaseNo); }}><ExternalLink className="h-3.5 w-3.5" />打开案件处置</button> : null}{artifactCaseNo && (artifact?.available_actions?.length ?? 0) > 0 ? <button type="button" onClick={() => { onClose(); onOpenCase(artifactCaseNo, true); }}><ShieldCheck className="h-3.5 w-3.5" />进入受控动作</button> : null}</div> : null}</article></div>;
          })}
        </div>}

        {!remediation ? <footer className="exception-ai-composer"><form onSubmit={(event) => void send(event)}><textarea ref={textareaRef} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void send(); } }} maxLength={4000} rows={3} placeholder="询问异常原因、风险或下一步动作" disabled={sending} /><div className="mt-2 flex items-center justify-between gap-3"><span className="text-xs font-bold text-muted-foreground">{input.length}/4000 · 建议需人工核对</span><div className="flex gap-1">{conversationNo && !sending ? <button className="exception-ai-icon-button text-red-600" type="button" title="删除当前会话" aria-label="删除当前会话" onClick={() => void removeConversation()}><Trash2 className="h-4 w-4" /></button> : null}{sending ? <button className="exception-ai-send" type="button" onClick={() => void stop()}><Square className="h-4 w-4" />停止</button> : <button className="exception-ai-send" type="submit" disabled={!input.trim()}><Send className="h-4 w-4" />发送</button>}</div></div></form>{error ? <p className="m-0 mt-2 text-xs font-black text-red-600" role="alert">{error}</p> : null}</footer> : null}
      </aside>
    </div>
  );
}
