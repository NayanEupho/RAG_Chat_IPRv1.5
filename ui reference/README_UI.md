# DevOps Agent Web UI

A modern, glassmorphic web interface for the DevOps Agent, built with **Next.js 16** and **React 19**.

![Next.js](https://img.shields.io/badge/Next.js-16.1-black)
![React](https://img.shields.io/badge/React-19.2-blue)
![TypeScript](https://img.shields.io/badge/TypeScript-5-blue)

## Features

- **Real-time Streaming Chat:** SSE-based streaming with live "thought" visualization
- **Session Management:** Create, view, switch, and delete conversation sessions
- **Live System Status:** Real-time indicators for LLM agents and MCP server health.
- **💓 Proactive Pulse Notifications:** Amber/Green status dots indicating real-time infrastructure connectivity.
- **🩺 Intelligent Diagnosis Cards:** specialized glassmorphic cards for AI-driven error explanations and fixes.
- **Agent Configuration:** In-app wizard for Smart/Fast/Embedding model setup
- **Human-in-the-Loop Safety:** Approval Cards for destructive action confirmation
- **Command Palette:** `Cmd/Ctrl + K` global shortcuts
- **Responsive Design:** Works on desktop and tablet layouts
- **Dark Theme:** Modern zinc/slate color palette with glassmorphism effects

## Quick Start

### Prerequisites
- Node.js 18+ or Bun
- **Backend API Server:** The UI requires the Python backend to be running.

### 1. Start the Backend Systems
Full system (API + all MCP servers):
```bash
# In a separate terminal
devops-agent start-all
```
*Wait for the "All servers started" message.*

### 2. Install UI Dependencies

```bash
cd ui
bun install
```

### Development

```bash
bun run dev   # Starts on http://localhost:3000
```

### Production Build

```bash
bun run build
bun run start
```

## Project Structure

```
ui/
├── src/
│   ├── app/                    # Next.js App Router
│   │   ├── layout.tsx          # Root layout with Sidebar + CommandMenu
│   │   ├── page.tsx            # Main page (Chat wrapper)
│   │   └── globals.css         # CSS variables, animations, utilities
│   ├── components/             # React components
│   │   ├── Chat.tsx            # Main chat interface with streaming
│   │   ├── ConfigModal.tsx     # Agent configuration wizard
│   │   ├── Sidebar.tsx         # Session list + system status
│   │   ├── CommandMenu.tsx     # Cmd+K command palette
│   │   ├── MCPSelector.tsx     # Mode selector dropdown
│   │   └── NewChatModal.tsx    # New session creation
│   └── lib/
│       └── api.ts              # API client (fetch wrappers)
├── package.json
└── README_UI.md                # This file
```

## Configuration

The UI connects to the backend API on port **8088** by default:

```
http://{current_hostname}:8088/api
```

This is auto-detected based on `window.location.hostname`, enabling seamless deployment on any host/IP.

## Key Components

| Component | Purpose |
|-----------|---------|
| `Chat.tsx` | Main chat interface. Handles SSE streaming, message rendering, approval cards |
| `ConfigModal.tsx` | 3-section wizard: Smart Agent, Fast Agent, Embedding Model config |
| `Sidebar.tsx` | Session list, live MCP/LLM status, server start controls |
| `CommandMenu.tsx` | Global `Cmd+K` palette using `cmdk` library |
| `MCPSelector.tsx` | Dropdown to select routing mode (Auto/Chat/Docker/K8s) |

## API Endpoints Used

| Function | Endpoint | Method |
|----------|----------|--------|
| `getSessions()` | `/api/sessions` | GET |
| `createSession()` | `/api/sessions` | POST |
| `deleteSession()` | `/api/sessions/:id` | DELETE |
| `getConfig()` | `/api/config` | GET |
| `updateConfig()` | `/api/config` | POST |
| `scanModels()` | `/api/models/scan` | POST |
| `getSystemStatus()` | `/api/status` | GET |
| `getPulseStatus()` | `/api/pulse/status` | GET |
| `getPulseIndex()` | `/api/pulse/index` | GET |
| `confirmAction()` | `/api/chat/confirm` | POST |

## Tech Stack

| Library | Version | Purpose |
|---------|---------|---------|
| Next.js | 16.1 | React framework with App Router |
| React | 19.2 | UI library |
| TypeScript | 5.x | Type safety |
| cmdk | 1.1 | Command palette |
| lucide-react | 0.562 | Icons |
| framer-motion | 12.x | Animations |
| react-markdown | 10.1 | Markdown rendering |
| sonner | 2.0 | Toast notifications |

## Styling

- **CSS Modules:** Component-scoped styles (`.module.css`)
- **CSS Variables:** Design tokens in `globals.css`
- **Glassmorphism:** `backdrop-blur` effects on cards and modals
- **Aurora Background:** Animated gradient background effect
- **💓 Zero-Latency Design Patterns**:
    - **Proactive Polling**: Frequent status checks for all MCPs.
    - **Optimistic Updates**: UI reflects action intent immediately.
    - **Thinking Visualization**: Real-time visualization of the agent's multi-tier reasoning (Fast/Smart).

## Related Documentation

- [Main README.md](../README.md) - Full project documentation
- [DEEP_DIVE_UI.md](./DEEP_DIVE_UI.md) - Detailed component documentation
- [ARCHITECTURE_AND_GUIDE.md](../ARCHITECTURE_AND_GUIDE.md) - Backend architecture
