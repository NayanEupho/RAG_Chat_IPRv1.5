"use client";

import { useEffect, useRef } from "react";
import { useAdminLiveLogs } from "@/components/use-admin-live-logs";

export default function LiveLogsPage() {
  const liveLogs = useAdminLiveLogs();
  const terminalRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    if (terminalRef.current) terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
  }, [liveLogs.logs.length]);

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Live Logs</h1>
          <p>Full-screen stream of backend admin job logs.</p>
        </div>
        <div className="actions">
          <button className="button" type="button" onClick={() => liveLogs.clear()}>Clear</button>
          <button className="button" type="button" onClick={() => void navigator.clipboard.writeText(liveLogs.logs.join("\n"))}>Copy</button>
        </div>
      </div>
      <pre className="terminal" ref={terminalRef} style={{ minHeight: "70vh" }}>{liveLogs.logs.length ? liveLogs.logs.join("\n") : "Waiting for live ingestion events..."}</pre>
    </section>
  );
}
