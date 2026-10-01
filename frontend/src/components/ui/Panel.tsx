import { clsx } from "clsx";
import type { ReactNode } from "react";

export function Panel({
  title,
  eyebrow,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={clsx("min-w-0 rounded-xl border border-line bg-panel", className)}>
      {(title || actions || eyebrow) && (
        <header className="flex items-start justify-between gap-3 px-4 pt-3.5 pb-2">
          <div className="min-w-0">
            {eyebrow && <div className="eyebrow mb-0.5">{eyebrow}</div>}
            {title && <h2 className="text-[14px] font-semibold text-fg">{title}</h2>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={clsx("px-4 pb-4", bodyClassName)}>{children}</div>
    </section>
  );
}
