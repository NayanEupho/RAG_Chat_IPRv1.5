from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich import box
import ollama
import time
from backend.config import set_main_model, set_embedding_model

console = Console()

def format_size(size_bytes: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"

def select_host(service_name: str) -> str:
    """Prompts user to select Local or Remote host."""
    console.print(f"\n[bold yellow]Configuration for {service_name}[/bold yellow]")
    console.print("Select Ollama Host:")
    console.print("1. Local (http://localhost:11434)")
    console.print("2. Remote (Custom URL)")
    
    choice = Prompt.ask("Select option", choices=["1", "2"], default="1")
    
    if choice == "1":
        return "http://localhost:11434"
    else:
        while True:
            url = Prompt.ask("Enter Remote Ollama URL (e.g. http://10.20.39.12:11434)")
            # Basic validation could go here
            if url:
                return url

def get_and_select_model(host: str, service_type: str) -> str:
    """Connects to host, lists models in a table, and asks for selection."""
    while True:
        try:
            with console.status(f"[bold green]Connecting to {host}...[/bold green]", spinner="dots"):
                client = ollama.Client(host=host)
                response = client.list()
                models = response.get('models', [])
            
            if not models:
                console.print(f"[red]No models found on {host}.[/red]")
                if Confirm.ask("Do you want to enter a different host?"):
                    host = select_host(service_type)
                    continue
                else:
                    raise ValueError("No models available.")

            # Create Table
            table = Table(title=f"Available Models on {host} ({service_type})", box=box.ROUNDED)
            table.add_column("No.", style="cyan", justify="right")
            table.add_column("Model Name", style="magenta")
            table.add_column("Size", style="green")
            table.add_column("Family", style="yellow")
            table.add_column("Quantization", style="blue")

            model_map = {}
            for idx, m in enumerate(models, 1):
                details = m.get('details', {})
                family = details.get('family', 'N/A')
                quant = details.get('quantization_level', 'N/A')
                size = format_size(m.get('size', 0))
                name = m['model']
                
                table.add_row(str(idx), name, size, family, quant)
                model_map[str(idx)] = name

            console.print(table)
            
            selection = Prompt.ask(f"Select {service_type} Model", choices=list(model_map.keys()))
            return model_map[selection], host # Return new host in case it changed

        except Exception as e:
            console.print(f"[red]Error connecting to {host}: {e}[/red]")
            if Confirm.ask("Try a different host?"):
                host = select_host(service_type)
            else:
                raise e

def run_interactive_config():
    while True:
        console.clear()
        console.print(Panel.fit("RAG Chat IPR - Configuration Wizard", style="bold blue"))
        
        try:
            # 1. Main Model Configuration
            main_host_initial = select_host("Main Model (Chat)")
            main_model, main_host = get_and_select_model(main_host_initial, "Chat")
            
            # 2. Embedding Model Configuration
            use_same = Confirm.ask(f"\nSelect Embedding model from the same Ollama host ({main_host})?", default=True)
            
            if use_same:
                embed_host_initial = main_host
            else:
                embed_host_initial = select_host("Embedding Model")
            
            embed_model, embed_host = get_and_select_model(embed_host_initial, "Embedding")

            # 3. Confirmation
            console.print("\n[bold white on black] Selected Configuration [/bold white on black]")
            console.print(f"Main Model (Chat):      [cyan]{main_model}[/cyan] @ [yellow]{main_host}[/yellow]")
            console.print(f"Embedding Model (RAG):  [cyan]{embed_model}[/cyan] @ [yellow]{embed_host}[/yellow]")
            
            if Confirm.ask("\nContinue with this configuration?", default=True):
                # Apply Configuration
                set_main_model(main_host, main_model)
                set_embedding_model(embed_host, embed_model)
                console.print("[bold green]Configuration Applied![/bold green]")
                break
            else:
                console.print("[yellow]Restarting configuration wizard...[/yellow]")
                time.sleep(1)
                continue

        except Exception as e:
            console.print(f"\n[bold red]An unexpected error occurred: {e}[/bold red]")
            if not Confirm.ask("Restart wizard?"):
                raise KeyboardInterrupt
