import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject
} from "react";
import { createPortal } from "react-dom";

type OverlayKind = "drawer" | "modal";

type OverlayEntry = {
  id: string;
  kind: OverlayKind;
  panelRef: RefObject<HTMLElement | null>;
  requestClose: () => void;
  returnFocusElement: HTMLElement | null;
};

type OverlayStackContextValue = {
  register: (entry: OverlayEntry) => () => void;
  stack: string[];
};

const OverlayStackContext = createContext<OverlayStackContextValue | null>(null);
const OVERLAY_BASE_Z_INDEX = 1000;
const OVERLAY_LAYER_STEP = 20;
const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "summary",
  "[contenteditable]:not([contenteditable='false'])",
  "[tabindex]:not([tabindex='-1'])"
].join(",");

function focusableElements(panel: HTMLElement) {
  return Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter((element) => {
    const style = window.getComputedStyle(element);
    return !element.hidden
      && !element.closest('[aria-hidden="true"]')
      && !element.closest("[inert]")
      && style.display !== "none"
      && style.visibility !== "hidden"
      && element.getClientRects().length > 0;
  });
}

function focusPanel(panel: HTMLElement | null, firstControl = false) {
  if (!panel) return;
  const target = firstControl ? focusableElements(panel)[0] ?? panel : panel;
  target.focus({ preventScroll: true });
}

export function OverlayStackProvider({ children }: { children: ReactNode }) {
  const entriesRef = useRef(new Map<string, OverlayEntry>());
  const stackRef = useRef<string[]>([]);
  const [stack, setStack] = useState<string[]>([]);

  const register = useCallback((entry: OverlayEntry) => {
    entriesRef.current.set(entry.id, entry);
    setStack((current) => {
      if (current.includes(entry.id)) return current;
      const next = [...current, entry.id];
      stackRef.current = next;
      return next;
    });
    const focusFrame = window.requestAnimationFrame(() => {
      const topId = stackRef.current[stackRef.current.length - 1];
      if (topId === entry.id) focusPanel(entry.panelRef.current);
    });

    return () => {
      window.cancelAnimationFrame(focusFrame);
      const registeredEntry = entriesRef.current.get(entry.id);
      entriesRef.current.delete(entry.id);
      setStack((current) => {
        const next = current.filter((id) => id !== entry.id);
        stackRef.current = next;
        return next;
      });

      window.setTimeout(() => {
        const returnTarget = registeredEntry?.returnFocusElement;
        if (returnTarget?.isConnected && !returnTarget.closest("[inert]")) {
          returnTarget.focus({ preventScroll: true });
          if (document.activeElement === returnTarget) return;
        }
        const topId = stackRef.current[stackRef.current.length - 1];
        focusPanel(topId ? entriesRef.current.get(topId)?.panelRef.current ?? null : null);
      }, 0);
    };
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const topId = stackRef.current[stackRef.current.length - 1];
      const topEntry = topId ? entriesRef.current.get(topId) : null;
      const panel = topEntry?.panelRef.current;
      if (!topEntry || !panel) return;

      if (event.key === "Escape" || event.key === "Esc") {
        event.preventDefault();
        event.stopImmediatePropagation();
        topEntry.requestClose();
        return;
      }

      if (event.key !== "Tab") return;
      const focusable = focusableElements(panel);
      if (focusable.length === 0) {
        event.preventDefault();
        focusPanel(panel);
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === panel || active === first || !panel.contains(active))) {
        event.preventDefault();
        last.focus({ preventScroll: true });
      } else if (!event.shiftKey && (active === last || !panel.contains(active))) {
        event.preventDefault();
        first.focus({ preventScroll: true });
      }
    };

    const onFocusIn = (event: FocusEvent) => {
      const topId = stackRef.current[stackRef.current.length - 1];
      const panel = topId ? entriesRef.current.get(topId)?.panelRef.current : null;
      if (panel && event.target instanceof Node && !panel.contains(event.target)) focusPanel(panel, true);
    };

    window.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("focusin", onFocusIn, true);
    return () => {
      window.removeEventListener("keydown", onKeyDown, true);
      document.removeEventListener("focusin", onFocusIn, true);
    };
  }, []);

  const hasOpenOverlay = stack.length > 0;
  useEffect(() => {
    if (!hasOpenOverlay) return;
    const body = document.body;
    const appRoot = document.getElementById("app");
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    const scrollbarGap = Math.max(0, window.innerWidth - document.documentElement.clientWidth);
    const bodyStyle = {
      position: body.style.position,
      top: body.style.top,
      left: body.style.left,
      right: body.style.right,
      width: body.style.width,
      overflow: body.style.overflow,
      paddingRight: body.style.paddingRight
    };
    const appState = appRoot ? {
      inert: appRoot.inert,
      ariaHidden: appRoot.getAttribute("aria-hidden")
    } : null;

    body.style.position = "fixed";
    body.style.top = `${-scrollY}px`;
    body.style.left = `${-scrollX}px`;
    body.style.right = "0";
    body.style.width = "100%";
    body.style.overflow = "hidden";
    if (scrollbarGap > 0) {
      const currentPadding = Number.parseFloat(window.getComputedStyle(body).paddingRight) || 0;
      body.style.paddingRight = `${currentPadding + scrollbarGap}px`;
    }
    if (appRoot) {
      appRoot.inert = true;
      appRoot.setAttribute("aria-hidden", "true");
    }

    return () => {
      Object.assign(body.style, bodyStyle);
      if (appRoot && appState) {
        appRoot.inert = appState.inert;
        if (appState.ariaHidden === null) appRoot.removeAttribute("aria-hidden");
        else appRoot.setAttribute("aria-hidden", appState.ariaHidden);
      }
      window.scrollTo(scrollX, scrollY);
    };
  }, [hasOpenOverlay]);

  const value = useMemo(() => ({ register, stack }), [register, stack]);
  return <OverlayStackContext.Provider value={value}>{children}</OverlayStackContext.Provider>;
}

export function useOverlayLayer({
  kind,
  panelRef,
  onEscape
}: {
  kind: OverlayKind;
  panelRef: RefObject<HTMLElement | null>;
  onEscape: () => void;
}) {
  const context = useContext(OverlayStackContext);
  if (!context) throw new Error("useOverlayLayer must be used inside OverlayStackProvider");
  const id = useId();
  const onEscapeRef = useRef(onEscape);
  onEscapeRef.current = onEscape;

  useLayoutEffect(() => {
    const returnFocusElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return context.register({
      id,
      kind,
      panelRef,
      requestClose: () => onEscapeRef.current(),
      returnFocusElement
    });
  }, [context.register, id, kind, panelRef]);

  const layerIndex = context.stack.indexOf(id);
  const isTop = layerIndex >= 0 && layerIndex === context.stack.length - 1;

  return {
    id,
    isTop,
    layerIndex: Math.max(0, layerIndex),
    zIndex: OVERLAY_BASE_Z_INDEX + Math.max(0, layerIndex) * OVERLAY_LAYER_STEP
  };
}

export function OverlayPortal({ children }: { children: ReactNode }) {
  if (typeof document === "undefined") return null;
  return createPortal(children, document.body);
}
