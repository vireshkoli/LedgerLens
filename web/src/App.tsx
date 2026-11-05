import { useEffect, useState } from "react";

import { checkApi, type ApiState } from "./apiStatus";

const LABELS: Record<ApiState, string> = {
  checking: "Checking the API",
  ready: "API and database are ready",
  unavailable: "API is unavailable",
};

export function App() {
  const [state, setState] = useState<ApiState>("checking");

  useEffect(() => {
    void checkApi().then(setState);
  }, []);

  return (
    <main>
      <h1>LedgerLens</h1>
      <p role="status">{LABELS[state]}</p>
    </main>
  );
}
