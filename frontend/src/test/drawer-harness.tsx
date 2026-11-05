import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { Drawer, Modal } from "../App";
import { OverlayStackProvider } from "../components/ui/overlay-stack";
import "../styles.css";

const tableRows = Array.from({ length: 8 }, (_, index) => ({
  id: index + 1,
  customer: `测试客户 ${index + 1}`,
  owner: index % 2 === 0 ? "销售一组" : "销售二组",
  status: index % 3 === 0 ? "待处理" : "推进中",
  note: "这是一段用于验证宽表格局部横向滚动和长文本展示的确定性测试内容。"
}));

function DrawerHarness() {
  const [primaryOpen, setPrimaryOpen] = useState(false);
  const [nestedOpen, setNestedOpen] = useState(false);
  const [thirdOpen, setThirdOpen] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  const closePrimary = () => {
    setModalOpen(false);
    setThirdOpen(false);
    setNestedOpen(false);
    setPrimaryOpen(false);
  };
  const closeNested = () => {
    setModalOpen(false);
    setThirdOpen(false);
    setNestedOpen(false);
  };

  return (
    <main className="min-h-[2200px] bg-background p-8 text-foreground" data-testid="background-page">
      <h1 className="text-2xl font-black">抽屉自动化测试工作台</h1>
      <p className="mt-2 max-w-2xl text-sm text-muted-foreground">该页面只使用本地固定数据，不访问后端接口。</p>
      <button type="button" className="project-button-primary mt-5" data-testid="open-primary" onClick={() => setPrimaryOpen(true)}>打开客户详情抽屉</button>
      <button type="button" className="project-button-secondary mt-5 ml-3" data-testid="background-action">后台操作</button>

      {primaryOpen ? (
        <Drawer
          title="客户详情：用于验证超长标题在扩展抽屉内能够完整换行且不遮挡右侧操作按钮"
          subtitle="QZKH0001003 · 上海弘洲陈路鲜鸡 · 全公司客户"
          onClose={closePrimary}
        >
          <div className="grid gap-4">
            <section className="project-drawer-overview">
              <div className="project-drawer-responsive-row">
                <div className="min-w-0">
                  <p className="text-xs font-black text-primary">CUSTOMER CONTEXT</p>
                  <h2 className="mt-1 break-words text-xl font-black">上海弘洲陈路鲜鸡</h2>
                </div>
                <button type="button" className="project-button-secondary" data-testid="open-nested" onClick={() => setNestedOpen(true)}>打开项目详情</button>
              </div>
              <div className="project-drawer-metric-grid" data-testid="metric-grid">
                {["资料状态", "销售额", "应收余额", "毛利"].map((label, index) => (
                  <div key={label} className="rounded-lg border border-border bg-muted p-3"><span className="text-xs font-bold text-muted-foreground">{label}</span><strong className="mt-2 block">{index === 0 ? "完整" : "0.00"}</strong></div>
                ))}
              </div>
              <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4" data-testid="legacy-grid">
                {["建档状态", "客户等级", "复核状态", "协同状态"].map((label) => (
                  <div key={label} className="rounded-lg border border-border bg-card p-3 text-sm font-bold">{label}</div>
                ))}
              </div>
              <div className="mt-3 grid gap-2 xl:grid-cols-[240px_minmax(0,1fr)_280px]" data-testid="permission-grid">
                <div className="rounded-lg border border-border bg-card p-3 text-sm font-bold">角色列表</div>
                <div className="rounded-lg border border-border bg-card p-3 text-sm font-bold">权限矩阵</div>
                <div className="rounded-lg border border-border bg-card p-3 text-sm font-bold">权限说明</div>
              </div>
            </section>

            <div className="project-drawer-split" data-testid="drawer-split">
              <section className="project-drawer-content-section">
                <div className="border-b border-border px-4 py-3"><h3 className="text-sm font-black">客户业务明细</h3></div>
                <div className="p-4">
                  <div className="overflow-x-auto" data-testid="wide-table-region" tabIndex={0}>
                    <table className="min-w-[1040px] w-full text-left text-sm">
                      <thead><tr>{["序号", "客户", "负责人", "状态", "更新时间", "说明"].map((label) => <th key={label} className="border-b border-border p-3">{label}</th>)}</tr></thead>
                      <tbody>{tableRows.map((row) => <tr key={row.id}><td className="border-b border-border p-3">{row.id}</td><td className="border-b border-border p-3">{row.customer}</td><td className="border-b border-border p-3">{row.owner}</td><td className="border-b border-border p-3">{row.status}</td><td className="border-b border-border p-3">2026-07-27</td><td className="border-b border-border p-3">{row.note}</td></tr>)}</tbody>
                    </table>
                  </div>
                </div>
              </section>
              <aside className="project-drawer-sidebar" data-testid="drawer-sidebar">
                <div className="project-drawer-side-card"><h3 className="project-drawer-side-card-title">联系人</h3><p className="mt-3 break-all text-sm">00000000000</p></div>
                <div className="project-drawer-side-card"><h3 className="project-drawer-side-card-title">关联职员</h3><p className="mt-3 text-sm">销售一组</p></div>
              </aside>
            </div>

            <div className="project-drawer-sticky-actions" data-testid="sticky-actions">
              <button type="button" className="project-button-secondary" onClick={closePrimary}>取消</button>
              <button type="button" className="project-button-primary">保存</button>
            </div>
            <details className="rounded-lg border border-border bg-card p-3">
              <summary className="cursor-pointer text-sm font-black" data-testid="system-summary">系统信息</summary>
              <p className="mt-2 text-xs text-muted-foreground">用于验证原生 summary 可以通过键盘到达。</p>
            </details>
          </div>

          {nestedOpen ? (
            <Drawer title="客户项目详情" subtitle="PROJECT-TEST-001 · 自动化测试项目" onClose={closeNested}>
              <div className="grid gap-4">
                <section className="project-drawer-section"><h3 className="project-drawer-section-title">项目进度</h3><p className="mt-3 text-sm">当前进度 60%，下一步核实客户配送要求。</p></section>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className="project-button-primary" data-testid="open-third" onClick={() => setThirdOpen(true)}>打开任务明细</button>
                  <button type="button" className="project-button-secondary" data-testid="open-modal" onClick={() => setModalOpen(true)}>打开确认弹窗</button>
                </div>
                {thirdOpen ? (
                  <Drawer title="任务明细" subtitle="TASK-TEST-001 · 测试客户" onClose={() => setThirdOpen(false)}>
                    <section className="project-drawer-section"><h3 className="project-drawer-section-title">任务内容</h3><input className="project-input mt-3 w-full" aria-label="任务说明" defaultValue="验证第三层抽屉焦点和关闭顺序" /><button type="button" className="project-button-primary mt-4">保存任务</button></section>
                  </Drawer>
                ) : null}
                {modalOpen ? (
                  <Modal title="确认项目操作" onClose={() => setModalOpen(false)}>
                    <p className="text-sm">该弹窗用于验证 Drawer 与 Modal 的混合层级。</p>
                    <button type="button" className="project-button-primary mt-4" data-testid="confirm-modal">确认</button>
                  </Modal>
                ) : null}
              </div>
            </Drawer>
          ) : null}
        </Drawer>
      ) : null}
    </main>
  );
}

createRoot(document.getElementById("app") as HTMLElement).render(
  <React.StrictMode>
    <OverlayStackProvider>
      <DrawerHarness />
    </OverlayStackProvider>
  </React.StrictMode>
);
