import React, { useId } from "react";

const VARIANTS = ["primary", "secondary", "navigation", "destructive", "quiet"];

export function Button({
  variant = "secondary",
  busy = false,
  disabled = false,
  disabledReason,
  children,
  type = "button",
  onClick,
  className = "",
  ...rest
}) {
  const kind = VARIANTS.includes(variant) ? variant : "secondary";
  const reasonId = useId();
  const refused = Boolean(disabled && disabledReason);
  const nativeDisabled = disabled && !disabledReason;
  const label = children;
  return (
    <span className="hud-btn-wrap">
      <button
        type={type}
        className={`hud-btn hud-btn--${kind}${busy ? " is-busy" : ""} ${className}`.trim()}
        disabled={nativeDisabled}
        aria-disabled={refused || busy ? true : undefined}
        aria-busy={busy || undefined}
        aria-describedby={refused ? reasonId : undefined}
        onClick={(event) => {
          if (busy || disabled) {
            event.preventDefault();
            return;
          }
          onClick?.(event);
        }}
        {...rest}
      >
        <span className="hud-btn__label">{label}</span>
        {busy ? <span className="hud-busy-spinner" aria-hidden="true" /> : null}
      </button>
      {refused ? (
        <span id={reasonId} className="hud-async__reason" title={disabledReason}>{disabledReason}</span>
      ) : null}
    </span>
  );
}
