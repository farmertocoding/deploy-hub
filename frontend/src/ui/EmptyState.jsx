import React from "react";
import { Button } from "./Button.jsx";

export function EmptyState({ sentence, button, onAction }) {
  return (
    <div className="hud-async" style={{ margin: "10vh auto", width: "fit-content", textAlign: "center" }}>
      <p>{sentence}</p>
      {button ? <Button variant="primary" onClick={onAction}>{button}</Button> : null}
    </div>
  );
}
