import { useMemo, useState } from "react";
import { defaultActionHandlers, hudGet, hudPost, presentExport } from "./contract.js";

export function useHudActions({ onNav, onSelect } = {}) {
  const [pending, setPending] = useState(null);
  const [lastCommand, setLastCommand] = useState(null);

  const run = async (cmd) => {
    const result = cmd.method === "GET"
      ? await hudGet(cmd.path)
      : await hudPost(cmd.path, cmd.body);
    if (result?.csv) presentExport(result);
    setLastCommand({ ...cmd, result });
    return result;
  };

  const handlers = useMemo(
    () => defaultActionHandlers({
      onNav,
      onSelect,
      onPending: setPending,
      onCommand: run,
    }),
    [onNav, onSelect],
  );

  return {
    pending,
    lastCommand,
    handlers,
    onCancelPending: () => setPending(null),
    onConfirmPending: async (item) => {
      await run(item);
      setPending(null);
    },
  };
}
