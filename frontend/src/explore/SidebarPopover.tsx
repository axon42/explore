import { useEffect, useId, useRef, useState, type ReactNode } from "react";

/** Native dismissal/focus behavior, with viewport-bounded placement for Firefox. */
export function SidebarPopover({ label, trigger, children, side = false, className = "" }: {
  label: string; trigger: ReactNode; children: (close: () => void) => ReactNode;
  side?: boolean; className?: string;
}) {
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  function close() { panel.current?.hidePopover(); button.current?.focus(); }
  useEffect(() => {
    if (!expanded) return;
    const hide = () => panel.current?.hidePopover();
    window.addEventListener("resize", hide);
    return () => window.removeEventListener("resize", hide);
  }, [expanded]);
  return <>
    <button ref={button} className={className} aria-label={label} aria-expanded={expanded}
      aria-controls={id} popoverTarget={id}>{trigger}</button>
    <div ref={panel} id={id} popover="auto" className="ex-sidebar-popover" aria-label={label}
      onKeyDown={e => {
        if (e.key === "Escape") { e.preventDefault(); close(); }
      }}
      onToggle={e => {
        const open = (e.nativeEvent as ToggleEvent).newState === "open";
        setExpanded(open);
        if (!open || !button.current || !panel.current) return;
        const anchor = button.current.getBoundingClientRect();
        const box = panel.current.getBoundingClientRect();
        const left = side && anchor.right + box.width + 20 < innerWidth ? anchor.right + 12 : anchor.left;
        const top = side ? anchor.bottom - box.height : anchor.bottom + 8 + box.height < innerHeight ? anchor.bottom + 8 : anchor.top - box.height - 8;
        panel.current.style.left = `${Math.max(12, Math.min(left, innerWidth - box.width - 12))}px`;
        panel.current.style.top = `${Math.max(12, Math.min(top, innerHeight - box.height - 12))}px`;
      }}>{children(close)}</div>
  </>;
}
