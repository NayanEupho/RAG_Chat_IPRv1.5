# DevOps Agent Web UI

A modern, glassmorphic web interface for the DevOps Agent, built with **Next.js 16** and **React 19**.

![Next.js](https://img.shields.io/badge/Next.js-16.1-black)
![React](https://img.shields.io/badge/React-19.2-blue)
![TypeScript](https://img.shields.io/badge/TypeScript-5-blue)

## Features

- **Real-time Streaming Chat:** SSE-based streaming with live "thought" visualization
- **Session Management:** Create, view, switch, and delete conversation sessions
- **Live System Status:** Real-time indicators for LLM agents and MCP server health (Smart, Fast, and Embedding agents)
- **Agent Configuration:** In-app wizard for Smart/Fast/Embedding model setup
- **Human-in-the-Loop Safety:** Approval Cards for destructive action confirmation
- **Command Palette:** `Cmd/Ctrl + K` global shortcuts
- **Responsive Design:** Works on desktop and tablet layouts
- **Dark Theme:** Modern zinc/slate color palette with glassmorphism effects

## Quick Start

### Prerequisites
- Node.js 18+ or Bun
- Backend API server running (see main README.md)

### Installation

```bash
cd ui
npm install   # or: bun install
```

### Development

```bash
npm run dev   # Starts on http://localhost:3000
```

### Production Build

```bash
npm run build
npm run start
```

## Detailed Documentation

- [README_UI.md](./README_UI.md) - Project overview and structure
- [DEEP_DIVE_UI.md](./DEEP_DIVE_UI.md) - Exhaustive component and protocol documentation
- [ui_suggestions.md](./ui_suggestions.md) - Roadmap and future improvements
