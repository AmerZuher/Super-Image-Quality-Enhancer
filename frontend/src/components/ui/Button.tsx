import { clsx } from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Spinner } from "./Spinner";

type Variant = "primary" | "ai" | "outline" | "ghost" | "danger";
type Size = "sm" | "md";

const variants: Record<Variant, string> = {
  primary: "bg-cyan text-on-cyan border-cyan hover:brightness-110 font-semibold",
  // Gold is reserved for actions that run an AI model.
  ai: "bg-gold text-on-gold border-gold hover:brightness-110 font-semibold",
  outline: "bg-panel-2 text-fg border-line-2 hover:border-cyan",
  ghost: "bg-transparent text-fg-2 border-transparent hover:bg-panel-2 hover:text-fg",
  danger: "bg-transparent text-err border-line-2 hover:border-err hover:bg-err-soft",
};

const sizes: Record<Size, string> = {
  sm: "h-7 px-2.5 text-xs gap-1.5",
  md: "h-9 px-3.5 text-[13px] gap-2",
};

/** Button styling for elements that aren't buttons, such as router links. */
export function buttonClasses(variant: Variant = "outline", size: Size = "md", className?: string): string {
  return clsx(
    "inline-flex items-center justify-center whitespace-nowrap rounded-lg border transition",
    "disabled:cursor-not-allowed disabled:opacity-60 [&_svg]:size-4 [&_svg]:shrink-0",
    variants[variant],
    sizes[size],
    className,
  );
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
  loading?: boolean;
}

export function Button({
  variant = "outline",
  size = "md",
  icon,
  loading = false,
  className,
  children,
  disabled,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={buttonClasses(variant, size, className)}
      {...rest}
    >
      {loading ? <Spinner /> : icon}
      {children}
    </button>
  );
}
