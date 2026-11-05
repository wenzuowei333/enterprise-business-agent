import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { motion, useReducedMotion } from "framer-motion";
import {
  BriefcaseBusiness,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  ClipboardList,
  LayoutDashboard,
  Plus,
  Search,
  ShieldCheck,
  UserCheck,
  UserRound,
  UsersRound
} from "lucide-react";

import { Badge } from "../design-system";
import { CrmWorkbenchMotionController } from "../components/crm/CrmWorkbenchMotionController";
import "../components/crm/crm-workbench.css";
import "../styles.css";

const SHELL_PREFERENCE_KEY = "project.shell.left-expanded.v1";

const queueItems = [
  { label: "继续草稿", value: "2", detail: "待提交", tone: "info" as const, icon: ClipboardList },
  { label: "待我补充", value: "1", detail: "补齐资料", tone: "warning" as const, icon: ClipboardCheck },
  { label: "客户资料", value: "查看", detail: "基础与经营", tone: "success" as const, icon: UserRound },
  { label: "待我审批", value: "3", detail: "处理队列", tone: "warning" as const, icon: ShieldCheck },
  { label: "待我支持", value: "1", detail: "协同事项", tone: "danger" as const, icon: BriefcaseBusiness }
];

const headerActions = [
  { label: "项目申请", icon: Plus },
  { label: "跟进填写", icon: ClipboardList },
  { label: "关联客户底盘", icon: UsersRound },
  { label: "我的提交", icon: UserCheck },
  { label: "我的工作", icon: ShieldCheck, primary: true }
];

const workspaceGroups = [
  {
    title: "客户全景",
    detail: "客户档案、客户开发与标签画像",
    icon: UserRound,
    entries: [
      { label: "关联客户底盘", detail: "查看客户基础资料", icon: UsersRound },
      { label: "客户开发", detail: "管理新客推进过程", icon: UserCheck },
      { label: "客户标签", detail: "查看结构化客户画像", icon: ClipboardCheck }
    ]
  },
  {
    title: "业务执行",
    detail: "项目、任务与一线跟进",
    icon: BriefcaseBusiness,
    entries: [
      { label: "项目列表", detail: "查看项目进展与目标", icon: BriefcaseBusiness },
      { label: "任务明细", detail: "处理客户任务", icon: ClipboardList },
      { label: "跟进记录", detail: "记录销售推进情况", icon: ClipboardCheck }
    ]
  },
  {
    title: "我的工作",
    detail: "审批、支持与提交记录",
    icon: ShieldCheck,
    entries: [
      { label: "我的审批", detail: "处理待审业务", icon: ShieldCheck },
      { label: "待支持事项", detail: "协同处理业务阻塞", icon: BriefcaseBusiness },
      { label: "我的提交", detail: "查看提交和驳回原因", icon: UserCheck }
    ]
  }
];

function UiUpgradeHarness() {
  const workbenchRef = useRef<HTMLElement | null>(null);
  const [controllerMounted, setControllerMounted] = useState(true);
  const [sidebarExpanded, setSidebarExpanded] = useState(() => window.localStorage.getItem(SHELL_PREFERENCE_KEY) === "true");
  const reduceMotion = useReducedMotion();
  const leftWidth = sidebarExpanded ? 224 : 64;
  const sidebarTransition = reduceMotion
    ? { duration: 0 }
    : { duration: 0.16, ease: [0.16, 1, 0.3, 1] as const };

  useEffect(() => {
    window.localStorage.setItem(SHELL_PREFERENCE_KEY, String(sidebarExpanded));
  }, [sidebarExpanded]);

  return (
    <div className="app-shell" data-testid="ui-upgrade-harness">
      <motion.aside
        initial={false}
        animate={{ width: leftWidth }}
        transition={sidebarTransition}
        className="app-sidebar"
        data-testid="app-sidebar"
        data-collapsed={!sidebarExpanded}
      >
        <div className="flex h-16 items-center gap-3 border-b border-border px-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-primary text-sm font-black text-primary-foreground">普</span>
          {sidebarExpanded ? <strong className="min-w-0 truncate text-sm">星河演示管理中心</strong> : null}
        </div>
        <nav className="app-sidebar-nav" aria-label="测试模块导航">
          {[
            ["经营首页", LayoutDashboard],
            ["客户 CRM", UserRound],
            ["项目执行", BriefcaseBusiness],
            ["审批中心", ShieldCheck]
          ].map(([label, Icon], index) => (
            <button
              key={String(label)}
              type="button"
              className="app-sidebar-nav-item"
              data-active={index === 1}
              title={!sidebarExpanded ? String(label) : undefined}
            >
              <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
              {sidebarExpanded ? <span className="truncate">{String(label)}</span> : <span className="sr-only">{String(label)}</span>}
            </button>
          ))}
        </nav>
        <button
          type="button"
          className="project-icon-button m-3"
          data-testid="toggle-sidebar"
          title={sidebarExpanded ? "收起导航" : "展开导航"}
          aria-label={sidebarExpanded ? "收起导航" : "展开导航"}
          onClick={() => setSidebarExpanded((value) => !value)}
        >
          {sidebarExpanded ? <ChevronLeft className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </button>
      </motion.aside>

      <div className="app-workspace" data-testid="app-workspace">
        <header className="app-topbar">
          <p className="m-0 text-sm font-bold">客户 CRM</p>
          <div className="relative hidden w-64 sm:block">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input className="project-input-sm w-full pl-9" aria-label="全局搜索" placeholder="搜索客户、项目或任务" />
          </div>
        </header>

        <div className="app-page-content">
          <main className="min-w-0 flex-1" data-testid="main-content">
            <section className="crm-shell">
              <div className="crm-nav-bar" role="navigation" aria-label="CRM 模块导航">
                {["CRM 首页", "客户全景", "业务执行", "我的工作"].map((label, index) => (
                  <button key={label} type="button" className={`crm-nav-tab ${index === 0 ? "crm-nav-tab-active" : ""}`}>
                    {label}
                    {index === 0 ? <span className="crm-nav-tab-indicator" /> : null}
                  </button>
                ))}
              </div>
            </section>

            <section
              ref={workbenchRef}
              className="crm-workbench"
              data-testid="crm-workbench"
              data-motion-state="pending"
              data-controller-mounted={controllerMounted}
            >
              {controllerMounted ? (
                <CrmWorkbenchMotionController scopeRef={workbenchRef} />
              ) : null}

              <header className="crm-workbench-header" data-crm-enter>
                <div className="crm-workbench-heading">
                  <p className="crm-workbench-kicker">CRM 首页</p>
                  <h1 className="crm-workbench-title">今日工作台</h1>
                  <p className="crm-workbench-summary">今日优先处理 3 条待审事项。</p>
                </div>
                <nav className="crm-workbench-actions" aria-label="CRM 快捷操作">
                  {headerActions.map((item) => {
                    const Icon = item.icon;
                    return (
                      <button key={item.label} type="button" className="crm-workbench-action" data-primary={item.primary || undefined}>
                        <Icon className="h-4 w-4" aria-hidden="true" />
                        <span>{item.label}</span>
                      </button>
                    );
                  })}
                </nav>
              </header>

              <section className="crm-workbench-queue" data-testid="crm-today-queue" data-crm-enter aria-label="今日工作队列">
                <div className="crm-workbench-queue-header">
                  <h2 className="crm-workbench-section-title">今日工作队列</h2>
                  <span className="crm-workbench-sync-state">已同步</span>
                </div>
                <div className="crm-workbench-queue-grid">
                  {queueItems.map((item) => {
                    const Icon = item.icon;
                    return (
                      <button key={item.label} type="button" className="crm-workbench-queue-item">
                        <span className="crm-workbench-queue-icon"><Icon className="h-4 w-4" aria-hidden="true" /></span>
                        <span className="crm-workbench-queue-copy">
                          <strong className="crm-workbench-queue-label">{item.label}</strong>
                          <span className="crm-workbench-queue-detail">{item.detail}</span>
                        </span>
                        <Badge tone={item.tone} density="compact">{item.value}</Badge>
                      </button>
                    );
                  })}
                </div>
              </section>

              <section className="crm-workbench-groups" data-testid="crm-workspace-groups" aria-label="CRM 工作分区">
                {workspaceGroups.map((group) => {
                  const Icon = group.icon;
                  return (
                    <section key={group.title} className="crm-workbench-group" data-crm-enter>
                      <header className="crm-workbench-group-header">
                        <span className="crm-workbench-group-icon"><Icon className="h-4 w-4" aria-hidden="true" /></span>
                        <div className="min-w-0">
                          <h2 className="crm-workbench-group-title">{group.title}</h2>
                          <p className="crm-workbench-group-desc">{group.detail}</p>
                        </div>
                      </header>
                      <div className="crm-workbench-entry-list">
                        {group.entries.map((entry) => {
                          const EntryIcon = entry.icon;
                          return (
                            <button key={entry.label} type="button" className="crm-workbench-entry">
                              <span className="crm-workbench-entry-icon"><EntryIcon className="h-3.5 w-3.5" aria-hidden="true" /></span>
                              <span className="crm-workbench-entry-copy">
                                <strong className="crm-workbench-entry-label">{entry.label}</strong>
                                <small className="crm-workbench-entry-desc">{entry.detail}</small>
                              </span>
                              <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                            </button>
                          );
                        })}
                      </div>
                    </section>
                  );
                })}
              </section>
            </section>
          </main>
          <aside className="relative hidden w-[52px] shrink-0 xl:block" aria-label="页面状态">
            <button type="button" className="grid h-[188px] w-[52px] place-items-center rounded-lg border border-border bg-card text-primary" title="展开页面状态">
              <ShieldCheck className="h-4 w-4" aria-hidden="true" />
            </button>
          </aside>
        </div>
      </div>

      <button
        type="button"
        className="sr-only"
        data-testid="toggle-motion-controller"
        aria-pressed={controllerMounted}
        onClick={() => setControllerMounted((value) => !value)}
      >
        切换动效控制器
      </button>
    </div>
  );
}

createRoot(document.getElementById("app") as HTMLElement).render(
  <React.StrictMode>
    <UiUpgradeHarness />
  </React.StrictMode>
);
