import * as React from "react";

import { cn } from "@/lib/utils";

export type Tone = "info" | "success" | "warning" | "danger" | "neutral";
export type Density = "comfortable" | "compact";

export type { MotionPreset } from "./motion";
export * from "./motion";

export type CardVariant = "surface" | "muted" | "plain";
export type CardPadding = "none" | "compact" | "standard";

export interface CardProps extends React.HTMLAttributes<HTMLElement> {
  as?: "section" | "article" | "div";
  variant?: CardVariant;
  padding?: CardPadding;
}

export function Card({
  as: Component = "section",
  variant = "surface",
  padding = "none",
  className,
  ...props
}: CardProps) {
  return (
    <Component
      className={cn("ds-card", className)}
      data-ui="card"
      data-variant={variant}
      data-padding={padding}
      {...props}
    />
  );
}

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg" | "icon";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  density?: Density;
  isLoading?: boolean;
  loadingLabel?: string;
  leadingIcon?: React.ReactNode;
  trailingIcon?: React.ReactNode;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "primary",
    size = "md",
    density = "comfortable",
    isLoading = false,
    loadingLabel = "处理中",
    leadingIcon,
    trailingIcon,
    disabled,
    className,
    children,
    type = "button",
    ...props
  },
  ref
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn("ds-button", className)}
      data-ui="button"
      data-variant={variant}
      data-size={size}
      data-density={density}
      aria-busy={isLoading || undefined}
      disabled={disabled || isLoading}
      {...props}
    >
      {isLoading ? (
        <span className="ds-button-loading-mark" aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
      ) : leadingIcon ? (
        <span className="shrink-0" aria-hidden="true">{leadingIcon}</span>
      ) : null}
      <span className="min-w-0 truncate">{children}</span>
      {isLoading ? <span className="sr-only">{loadingLabel}</span> : null}
      {!isLoading && trailingIcon ? <span className="shrink-0" aria-hidden="true">{trailingIcon}</span> : null}
    </button>
  );
});

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
  density?: Density;
  leadingIcon?: React.ReactNode;
}

export function Badge({
  tone = "neutral",
  density = "comfortable",
  leadingIcon,
  className,
  children,
  ...props
}: BadgeProps) {
  return (
    <span
      className={cn("ds-badge", className)}
      data-ui="badge"
      data-tone={tone}
      data-density={density}
      {...props}
    >
      {leadingIcon ? <span className="shrink-0" aria-hidden="true">{leadingIcon}</span> : null}
      <span className="min-w-0 break-words">{children}</span>
    </span>
  );
}

export interface PageHeaderProps extends Omit<React.HTMLAttributes<HTMLElement>, "title"> {
  context?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  icon?: React.ReactNode;
  actions?: React.ReactNode;
  secondaryActions?: React.ReactNode;
}

export function PageHeader({
  context,
  title,
  description,
  icon,
  actions,
  secondaryActions,
  className,
  ...props
}: PageHeaderProps) {
  return (
    <header className={cn("ds-page-header", className)} data-ui="page-header" {...props}>
      <div className="ds-page-header-copy">
        {context ? <p className="ds-page-header-context">{context}</p> : null}
        <div className="ds-page-header-title-row">
          {icon ? <span className="ds-page-header-icon" aria-hidden="true">{icon}</span> : null}
          <div className="min-w-0">
            <h1 className="ds-page-header-title">{title}</h1>
            {description ? <p className="ds-page-header-description">{description}</p> : null}
          </div>
        </div>
      </div>
      {actions || secondaryActions ? (
        <div className="ds-page-header-actions">
          {secondaryActions}
          {actions}
        </div>
      ) : null}
    </header>
  );
}

export interface ToolbarProps extends React.HTMLAttributes<HTMLDivElement> {
  actions?: React.ReactNode;
}

export function Toolbar({ actions, className, children, ...props }: ToolbarProps) {
  return (
    <div className={cn("ds-toolbar", className)} data-ui="toolbar" {...props}>
      <div className="ds-toolbar-content">{children}</div>
      {actions ? <div className="ds-toolbar-actions">{actions}</div> : null}
    </div>
  );
}

export interface TabItem {
  id: string;
  label: React.ReactNode;
  icon?: React.ReactNode;
  count?: number;
  disabled?: boolean;
}

export interface TabsProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "onChange"> {
  items: TabItem[];
  value: string;
  onChange: (value: string) => void;
  density?: Density;
  ariaLabel: string;
}

export function Tabs({ items, value, onChange, density = "comfortable", ariaLabel, className, ...props }: TabsProps) {
  const handleKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const tabList = event.currentTarget.closest('[role="tablist"]');
    if (!tabList) return;
    const tabs = Array.from(tabList.querySelectorAll<HTMLButtonElement>('[role="tab"]:not(:disabled)'));
    if (tabs.length === 0) return;
    const currentIndex = tabs.indexOf(event.currentTarget);
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? tabs.length - 1
        : (currentIndex + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    const nextTab = tabs[nextIndex];
    event.preventDefault();
    nextTab.focus();
    onChange(nextTab.dataset.value ?? "");
  };

  return (
    <div
      className={cn("ds-tabs", className)}
      data-ui="tabs"
      data-density={density}
      role="tablist"
      aria-label={ariaLabel}
      {...props}
    >
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          className="ds-tab"
          role="tab"
          aria-selected={value === item.id}
          tabIndex={value === item.id ? 0 : -1}
          data-value={item.id}
          disabled={item.disabled}
          onClick={() => onChange(item.id)}
          onKeyDown={handleKeyDown}
        >
          {item.icon ? <span aria-hidden="true">{item.icon}</span> : null}
          <span>{item.label}</span>
          {typeof item.count === "number" ? <span className="ds-tab-count">{item.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

export interface StatStripItem {
  id: string;
  label: React.ReactNode;
  value: React.ReactNode;
  meta?: React.ReactNode;
  tone?: Tone;
  onSelect?: () => void;
}

export interface StatStripProps extends React.HTMLAttributes<HTMLDivElement> {
  items: StatStripItem[];
  ariaLabel: string;
}

const statColumnClass = [
  "lg:grid-cols-1",
  "lg:grid-cols-1",
  "lg:grid-cols-2",
  "lg:grid-cols-3",
  "lg:grid-cols-4",
  "lg:grid-cols-5"
] as const;

export function StatStrip({ items, ariaLabel, className, ...props }: StatStripProps) {
  const columnClass = statColumnClass[Math.min(items.length, 5)];
  return (
    <div
      className={cn("ds-stat-strip", columnClass, className)}
      data-ui="stat-strip"
      role="group"
      aria-label={ariaLabel}
      {...props}
    >
      {items.map((item) => {
        const content = (
          <>
            <span className="ds-stat-item-label">{item.label}</span>
            <span className="ds-stat-item-value">{item.value}</span>
            {item.meta ? <span className="ds-stat-item-meta">{item.meta}</span> : null}
          </>
        );
        return item.onSelect ? (
          <button
            key={item.id}
            type="button"
            className="ds-stat-item"
            data-tone={item.tone ?? "neutral"}
            onClick={item.onSelect}
          >
            {content}
          </button>
        ) : (
          <div key={item.id} className="ds-stat-item" data-tone={item.tone ?? "neutral"}>
            {content}
          </div>
        );
      })}
    </div>
  );
}

export interface EmptyStateProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  icon?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
}

export function EmptyState({ icon, title, description, action, className, ...props }: EmptyStateProps) {
  return (
    <div className={cn("ds-empty-state", className)} data-ui="empty-state" {...props}>
      {icon ? <span className="ds-empty-state-icon" aria-hidden="true">{icon}</span> : null}
      <h3 className="ds-empty-state-title">{title}</h3>
      {description ? <p className="ds-empty-state-description">{description}</p> : null}
      {action ? <div className="ds-empty-state-action">{action}</div> : null}
    </div>
  );
}

export interface DataTableShellProps extends Omit<React.HTMLAttributes<HTMLElement>, "title"> {
  title: React.ReactNode;
  description?: React.ReactNode;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  toolbar?: React.ReactNode;
  density?: Density;
  isEmpty?: boolean;
  emptyState?: React.ReactNode;
  ariaLabel?: string;
}

export function DataTableShell({
  title,
  description,
  meta,
  actions,
  toolbar,
  density = "compact",
  isEmpty = false,
  emptyState,
  ariaLabel,
  className,
  children,
  ...props
}: DataTableShellProps) {
  return (
    <section
      className={cn("ds-data-table-shell", className)}
      data-ui="data-table-shell"
      data-density={density}
      aria-label={ariaLabel}
      {...props}
    >
      <div className="ds-data-table-header">
        <div className="min-w-0">
          <h2 className="ds-data-table-title">{title}</h2>
          {description ? <p className="ds-data-table-description">{description}</p> : null}
          {meta ? <p className="ds-data-table-meta">{meta}</p> : null}
        </div>
        {actions ? <div className="ds-toolbar-actions shrink-0">{actions}</div> : null}
      </div>
      {toolbar}
      {isEmpty ? emptyState : <div className="ds-data-table-content">{children}</div>}
    </section>
  );
}

export interface FormFieldProps extends React.HTMLAttributes<HTMLDivElement> {
  label: React.ReactNode;
  htmlFor: string;
  hint?: React.ReactNode;
  error?: React.ReactNode;
  required?: boolean;
}

export function FormField({ label, htmlFor, hint, error, required, className, children, ...props }: FormFieldProps) {
  return (
    <div className={cn("ds-form-field", className)} data-ui="form-field" {...props}>
      <label className="ds-form-label" htmlFor={htmlFor}>
        {label}
        {required ? <span className="ds-form-required" aria-hidden="true"> *</span> : null}
      </label>
      {children}
      {error ? <p className="ds-form-error" role="alert">{error}</p> : hint ? <p className="ds-form-hint">{hint}</p> : null}
    </div>
  );
}
