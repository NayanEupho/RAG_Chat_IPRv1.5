# IPR RAG Chat - Frontend

This is the **Next.js** web interface for the IPR RAG Chat system. It features a premium, high-performance design built with **Vanilla CSS** and **Framer Motion**.

## 🚀 Getting Started

1.  **Install Dependencies**:
    ```bash
    bun install
    ```

2.  **Start Development Server**:
    ```bash
    bun dev
    ```

3.  **Open Browser**: Visit `http://localhost:3000`.

## 🛠 Tech Stack
- **Next.js 15+**: App Router for stateful navigation.
- **Vanilla CSS**: Custom Design System with aurora effects and glassmorphism.
- **Lucide React**: Clean iconography.
- **Framer Motion**: Smooth micro-animations and transitions.
- **Fetch API**: Real-time streaming integration with the FastAPI backend.

## 📁 Key Files
- `src/components/ChatInterface.tsx`: Main chat logic and UI.
- `src/hooks/useChat.ts`: Custom hook for SSE streaming, history loading, and request cancellation.
- `src/app/globals.css`: The entire Design System (Variables, Components, Utilities).

## 🛑 Stop Generation
The frontend supports immediate termination of LLM requests via `AbortController`. This is triggered by the "Stop" button in the header.

## 📄 Source Viewer
Citations are interactive. Clicking a document tag will open a modal with the retrieved text context directly in the UI.
