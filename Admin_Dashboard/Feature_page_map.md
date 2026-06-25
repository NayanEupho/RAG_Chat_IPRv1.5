### 1. Monitoring (Main Page)

This serves as the real-time operational hub for the application, leveraging Server-Sent Events (SSE) to display live system health without requiring page refreshes.

* **View Active Processing:** The administrator lands here to see live progress bars for all active batches, calculated dynamically based on document stages like `PARSING`, `NORMALIZING`, and `CHUNKING`.


* **Handle Immediate Failures:** A dedicated "Recent Failures" section allows the admin to spot immediate issues, such as a `docling` parser failure, and click **"Retry"** directly from the dashboard.


* **Review Daily Output:** A "Completed Today" list shows successfully indexed documents alongside their chunk counts.


* **Manage Notifications:** A persistent bell icon tracks unread alerts across the system, popping open a panel to display `STAGE_UPDATE`, `ERROR`, or `SUCCESS` events.



### 2. Control Panel

This page acts as the global command center for pipeline infrastructure and AI configuration.

* **Configure LLM Endpoints:** The admin registers network-accessible endpoints for normalization models (e.g., `[http://10.100.0.5:8000/v1](http://10.100.0.5:8000/v1)` for `qwen3-70b`).


* **Manage System Status:** The admin can monitor backend worker connections (like Celery and Redis) and ensure the Qdrant vector database is online and accepting connections.


* **Set Global Overrides:** The admin defines the overarching fallback defaults for the `pymupdf4llm` and `docling` parsers before any batch is created.



### 3. Upload (Ingestion Initiation & Active Processing)

This section has been expanded to encompass the entire front half of the ingestion flow. It handles file staging, configuration, and the monitoring of the parsing/normalization jobs.

* **Stage Files:** The admin drags and drops PDF or DOCX files (up to 500 MB each) into the queue.


* **Configure Batch Pipeline:** Instead of navigating away, the admin configures the batch directly here. They select which parsers to run and toggle LLM normalization on or off.


* **Apply Granular Overrides:** The admin targets specific documents in the upload queue to apply custom configurations, such as skipping normalization for a specific safety manual while running it on everything else.


* **Submit & Track:** The admin clicks **"Save & Submit"**. The UI transitions to a live tracking view where they watch parallel `ParseVariant` and `NormVariant` Celery jobs execute in real-time.


* **Recover Failures Instantly:** If a file throws a `DocumentProcessingError` during parsing, the admin clicks **"Retry Parse"** to cleanly re-queue that exact job without contaminating sibling jobs.



### 4. Review (The Final Polish)

Once parsing and normalization conclude, documents flow into this page. This is the manual intervention checkpoint before data enters the vector database.

* **Compare Variants:** The admin is presented with the generated outputs. If multiple parsers and models ran, they compare outputs (e.g., `docling` vs. `pymupdf4llm` base text) and click **"Select this for Review"**.


* **Trigger Late Normalization:** If the admin bypassed normalization during the Upload phase, they can click **"Trigger LLM Normalization"** right from the review interface to generate a normalized file on the fly.


* **Edit Content Inline:** The admin uses the built-in CodeMirror 6 markdown editor to fix formatting errors, delete sensitive information, or restructure headers directly in the browser.


* **Upload External Replacements:** The admin clicks **"Choose .md file to upload"** to overwrite the system-generated text with a locally heavily edited markdown file.


* **Approve & Index:** The admin clicks **"Approve & Index ✓"**. This finalizes the `approved.md` file, triggers a 60-second asynchronous cleanup of unused variant files, and fires the `CHUNK_PENDING` job to send data to Qdrant.



### 5. Document Warehouse

This is the permanent, read-only repository for all historical, fully processed files.

* **Search the Archive:** The admin searches the entire organization's repository by `original_filename` or filters by processing status and date.


* **Download Canonical Files:** The admin clicks dynamic badges to download any of the five surviving canonical files: the `source_file`, `raw_md`, `parsed_md`, `normalized_md`, or the final `review_approved_md`.


* **Action Shortcuts:** The admin can jump straight into the Review page for pending files or trigger a retry for failed historical documents directly from the warehouse table.



### 6. Chunks

This page provides a microscopic view into how the text was mathematically divided before embedding.

* **Search Semantic Payloads:** The admin performs full-text searches against the Qdrant payload text to find specific paragraphs or data points.


* **Audit Chunk Metadata:** By expanding a row, the admin verifies the exact token count, character count, source page numbers, and the hierarchical section path (e.g., "Chapter 1 › Introduction").


* **Verify Indexing Chronology:** The admin can check the exact timestamp an individual chunk was indexed into the vector store.



### 7. Vector Stats

This page provides high-level telemetry regarding the Qdrant database and overall embedding footprint.

* **Monitor Collection Health:** The admin views the total volume of chunks currently indexed across all batches in the Qdrant collection.


* **Track Model Dimensions:** The admin reviews which embedding models were used for different documents and verifies the dimension sizes of the vectors stored.


* **Assess Database Utilization:** The admin evaluates the overall token and character footprint of the ingested data to forecast database sizing and LLM context window limits.



### 8. History & Logs

This is the forensic analysis zone for deep technical audits and performance tracking.

* **Filter Pipeline Telemetry:** The admin searches append-only PostgreSQL logs by `DEBUG`, `INFO`, `WARN`, or `ERROR` levels.


* **Expand Stack Traces:** When investigating a failed job, the admin expands the log entry to read the raw Python traceback (e.g., `XRefError: table corrupted at offset`) without needing terminal access.


* **Analyze Batch Timelines:** The admin opens a specific historical batch to see the exact wall-clock time it took to complete each phase of ingestion, from initial upload to final indexing.


* **Export JSON Reports:** The admin clicks **"Download Batch Report"** to extract a raw JSON dump of the batch configuration, document statistics, and processing timeline for external compliance records.
