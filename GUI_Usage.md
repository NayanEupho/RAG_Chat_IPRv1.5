# GUI Usage Guide (Platinum Edition)

The Frontend is a modern **Next.js 15** application built with a premium "Glassmorphic" design, optimized for high-intelligence research.

---

## 🚀 Key Interface Features

### 1. Intelligence Mode Selector 🕹️
Located directly next to the chat input, this tool allows you to override the agent's brain:
- **Auto**: The default. The agent decides if it needs the Knowledge Base or just a chat.
- **RAG**: Forces the agent to retrieve data, even for general questions.
- **Chat**: Disables the Knowledge Base for pure LLM performance.

### 2. The Thinking Timeline 🧠
A collapsible, real-time visualization of the agent's logic:
- **Protocol Initiated**: Handshake with the LangGraph orchestrator.
- **Analyzing Intent**: The router deciding the path (Chat vs RAG).
- **Refining Query**: The rewriter optimizing your prompt for vector search.
- **Searching Documents**: The retriever fetching chunks.
- **Generating Answer**: The final synthesis stage.

### 3. Smart @Mention System 📍
Type `@` in the chat to open a live-filtered list of your knowledge base.
- **Interactive Search**: Use arrow keys or your mouse to select files.
- **Multi-Tagging**: Mention multiple files (e.g., *"Compare @FileA and @FileB"*) to trigger the **Semantic Segmentation** engine.

### 4. Fragmented Source Strips 📑
When retrieval occurs, interactive source cards appear at the top of the AI's response:
- **Targeted Highlighting**: If a search was focused on specific `@` tags, the source cards glow with a cyan border.
- **Context Preview**: Cards show a snippet of the text before you even click them.
- **Frosted Modals**: Click any card to read the full source text in a premium overlay.

---

## 🛠 Advanced Controls

- **Stop Generation**: Use the **Square Icon** to immediately kill an LLM stream.
- **Session Cleanup**: Use the **Trash Icon** in the sidebar to permanently delete conversations.
- **Knowledge Viewer**: Click the **Database Icon** to see a grid view of all indexed files.

---

## 🚀 Frontend Deployment Commands

For a stable, high-performance experience, use the production workflow instead of the development server.

### 1. Command Summary
| Environment | Action | Command |
| :--- | :--- | :--- |
| **Development** | Start Dev Server | `bun dev` |
| **Production** | Build Application | `bun run build` |
| **Production** | Serve Build | `bun run start` |

### 2. The Production Workflow
Follow these steps when moving the UI to a production or shared network environment:
1.  **Build Phase**: Run `bun run build` in the `frontend/` directory. This creates a highly optimized `.next` folder.
2.  **Start Phase**: Run `bun run start`. This server is optimized for high concurrency and low memory usage.
3.  **Persistence**: (Recommended) Use a process manager like **PM2** to keep the frontend alive:
    ```bash
    pm2 start "bun run start" --name "rag-gui"
    ```

---

## 🎨 Design Philosophy
The UI follows a **Glass-Aura** aesthetic:
- **Depth**: Multi-layered transparency with backdrop blurring.
- **Feedback**: Staggered "Slide-Up" animations for message entry.
- **Utility**: Zero Content Layout Shift (CLS) through fixed-height input containers.

## ❓ Troubleshooting
- **Missing @Files**: Ensure the files are present in the `upload_docs/` folder. The system auto-indexes new files in seconds.
- **Slow Responses**: Heavy PDF parsing (100MB+) might cause a slight delay in the "Searching" status.
- **History Mismatch**: If you switch models in the backend, use the **Refresh** or **Delete Session** button to sync the UI context.
- **Config Persistence**: The system now remembers your backend host and model settings via the **Hybrid Configuration System**. Once set, you won't need to re-configure on every launch.
