export default function AboutPage() {
  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>About</h1>
          <p>RAG administration workspace for ingestion, review, retrieval inventory, and document removal.</p>
        </div>
      </div>
      <div className="panel">
        <h2>Dashboard Scope</h2>
        <p className="muted">
          This dashboard manages admin-batch ingestion while preserving backwards compatibility with legacy files indexed through the upload_docs file watcher.
        </p>
      </div>
    </section>
  );
}
