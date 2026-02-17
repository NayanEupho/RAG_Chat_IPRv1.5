"""
RAG Chat CLI Client
-------------------
A rich-formatted command line interface for interacting with the RAG Chat API.
Supports streaming responses, status updates, and session persistence.
"""

import asyncio
import argparse
import aiohttp
import sys
import os
import json
from rich.console import Console
from rich.markdown import Markdown
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text
from rich.panel import Panel

# Initialize Rich console for beautiful terminal output
console = Console()
SESSION_FILE = ".cli_session"

def get_session_id():
    """
    Retrieves or generates a unique session ID for the CLI client.
    Persistence is handled via the .cli_session file.
    """
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, 'r') as f:
             return f.read().strip()
    
    # Generate a new session ID based on PID and timestamp
    session_id = f"cli_{os.getpid()}_{int(asyncio.get_event_loop().time())}"
    with open(SESSION_FILE, 'w') as f:
        f.write(session_id)
    return session_id

async def chat_loop(api_url: str):
    """
    Main interactive chat loop.
    Handles user input, API requests, and streaming response rendering.
    """
    session_id = get_session_id()
    console.print(f"[bold green]Connected to RAG Chat v1.6 (Session: {session_id})[/bold green]")
    console.print("Type 'exit' to quit. Streaming & Status enabled.")
    
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                user_input = console.input("\n[bold cyan]You > [/bold cyan]")
                if user_input.lower() in ["exit", "quit"]:
                    break
                
                if not user_input.strip():
                    continue

                full_response = ""
                current_status = "Initializing..."
                intent = None
                sources = []
                
                # Live Display for Streaming
                with Live(Spinner('dots', text=current_status), refresh_per_second=10) as live:
                    
                    payload = {"message": user_input, "session_id": session_id}
                    
                    try:
                        async with session.post(f"{api_url}/api/chat/stream", json=payload) as resp:
                            if resp.status != 200:
                                live.update(f"[red]Error {resp.status}[/red]")
                                continue
                                
                            current_event_type = None
                            
                            async for line in resp.content:
                                decoded_line = line.decode('utf-8').strip()
                                if not decoded_line: continue
                                
                                # SSE Parsing
                                if decoded_line.startswith("event:"):
                                    current_event_type = decoded_line.replace("event: ", "").strip()
                                    continue
                                
                                if decoded_line.startswith("data:"):
                                    data_str = decoded_line.replace("data: ", "").strip()
                                    
                                    if current_event_type == "status":
                                        current_status = data_str
                                        live.update(Spinner('dots', text=f"[yellow]{current_status}[/yellow]"))
                                        
                                    elif current_event_type == "token":
                                        token = json.loads(data_str)
                                        full_response += token
                                        # Update Live View with partial markdown
                                        live.update(Panel(Markdown(full_response), title=f"[magenta]Bot ({current_status})[/magenta]"))
                                        
                                    elif current_event_type == "end":
                                        meta = json.loads(data_str)
                                        intent = meta.get("intent")
                                        sources = meta.get("sources")
                                        current_status = "Done"
                                        
                    except Exception as e:
                        live.update(f"[red]Connection Error: {e}[/red]")

                # Final Print (once stream ends, Live context exits, we print final state)
                console.print(Panel(Markdown(full_response), title=f"[boldMagenta]Bot ({intent})[/boldMagenta]"))
                
                if sources:
                    console.print("[dim]Sources:[/dim]")
                    for src in sources:
                         console.print(f"[dim]- {src.splitlines()[0]}[/dim]")

            except KeyboardInterrupt:
                break
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                break

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000", help="API URL")
    args = parser.parse_args()
    
    try:
        asyncio.run(chat_loop(args.url))
    except KeyboardInterrupt:
        pass
