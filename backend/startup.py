from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich import box
import ollama
import time
from backend.config import set_main_model, set_embedding_model, set_vlm_model

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

def validate_model_on_host(host: str, model_name: str, service_type: str) -> bool:
    """Verifies if host is reachable and if model exists on it."""
    try:
        with console.status(f"[bold yellow]Validating {service_type} Config...[/bold yellow]", spinner="dots"):
            client = ollama.Client(host=host)
            # Step 1: Check Connectivity
            try:
                response = client.list()
            except Exception as e:
                console.print(f"[bold red]❌ [CONNECTIVITY ERROR][/bold red] "
                              f"Failed to reach {service_type} host at [yellow]{host}[/yellow]")
                console.print(f"[dim]Details: {e}[/dim]")
                return False
            
            # Step 2: Check Model Existence
            models = response.get('models', [])
            model_names = [m['model'] for m in models]
            
            # Check for exact match or tag-less match
            if model_name in model_names or any(m.startswith(f"{model_name}:") for m in model_names):
                console.print(f"[bold green]✓[/bold green] {service_type} Config Verified: "
                              f"[cyan]{model_name}[/cyan] found on [yellow]{host}[/yellow].")
                return True
            else:
                console.print(f"[bold red]❌ [AVAILABILITY ERROR][/bold red] "
                              f"Model [cyan]{model_name}[/cyan] not found on [yellow]{host}[/yellow].")
                console.print(f"[dim]Available models on this host: {', '.join(model_names[:5])}{'...' if len(model_names) > 5 else ''}[/dim]")
                return False
                
    except Exception as e:
        console.print(f"[bold red]❌ Unexpected Validation Error:[/bold red] {e}")
        return False

def check_for_env_config() -> bool:
    """Checks for .env file, shows values, prompts user, and VALIDATES if confirmed."""
    import os
    env_path = ".env"
    
    if not os.path.exists(env_path):
        return False
        
    # Manual lightweight parsing to avoid dependency
    env_vars = {}
    try:
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, val = line.split('=', 1)
                env_vars[key.strip()] = val.strip().strip('"').strip("'")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not read .env: {e}[/yellow]")
        return False
        
    required_keys = ["RAG_MAIN_HOST", "RAG_MAIN_MODEL", "RAG_EMBED_HOST", "RAG_EMBED_MODEL"]
    if all(k in env_vars for k in required_keys):
        from rich.text import Text
        console.print(Panel.fit("[bold green].env Configuration Detected[/bold green]", style="bold green"))
        
        # We manually construct text to avoid Rich interpreting colons in names as style tags
        def print_var(label, value):
            t = Text(label)
            t.append(value, style="cyan")
            console.print(t)

        print_var("Main Host:  ", env_vars['RAG_MAIN_HOST'])
        print_var("Main Model: ", env_vars['RAG_MAIN_MODEL'])
        print_var("Embed Host: ", env_vars['RAG_EMBED_HOST'])
        print_var("Embed Model:", env_vars['RAG_EMBED_MODEL'])
        
        # Display VLM config if present
        vlm_model = env_vars.get('RAG_VLM_MODEL', 'False')
        if vlm_model.lower() not in ['false', '0', 'no', 'off', '']:
            print_var("VLM Host:   ", env_vars.get('RAG_VLM_HOST', 'N/A'))
            print_var("VLM Model:  ", vlm_model)
        else:
            console.print("[dim]VLM OCR:     Disabled (using Docling)[/dim]")

        
        if Confirm.ask("\nImport settings from .env and skip wizard?", default=True):
            # NEW: Post-Confirmation Validation
            main_ok = validate_model_on_host(env_vars['RAG_MAIN_HOST'], env_vars['RAG_MAIN_MODEL'], "Main (Chat)")
            embed_ok = validate_model_on_host(env_vars['RAG_EMBED_HOST'], env_vars['RAG_EMBED_MODEL'], "Embedding (RAG)")
            
            if main_ok and embed_ok:
                set_main_model(env_vars['RAG_MAIN_HOST'], env_vars['RAG_MAIN_MODEL'])
                set_embedding_model(env_vars['RAG_EMBED_HOST'], env_vars['RAG_EMBED_MODEL'])
                
                # Set VLM config if present
                vlm_model = env_vars.get('RAG_VLM_MODEL', 'False')
                if vlm_model.lower() not in ['false', '0', 'no', 'off', '']:
                    vlm_host = env_vars.get('RAG_VLM_HOST', '')
                    if vlm_host:
                        set_vlm_model(vlm_host, vlm_model)
                
                console.print("[bold green]Configuration Loaded from .env and Verified![/bold green]")
                time.sleep(1) # Visual feedback
                return True

            else:
                console.print("[bold yellow]\n⚠️ .env Validation failed. Falling back to Configuration Wizard...[/bold yellow]")
                time.sleep(2)
                return False
            
    return False

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
    # 0. Check for Hybrid .env Config
    if check_for_env_config():
        return

    import os
    while True:
        console.clear()
        
        console.print(Panel.fit("RAG Chat IPR - Configuration Wizard", style="bold blue", title="Setup"))

        # Only show detailed example if .env doesn't exist
        if not os.path.exists(".env"):
             console.print("\n[bold yellow]Tip: Make a .env file for default/faster configuration set-up[/bold yellow]")
             example_text = (
                "# RAG Chat IPR - Configuration File\n\n"
                "# 1. Main Chat Model (Inference)\n"
                "RAG_MAIN_HOST=\"http://localhost:11434\"\n"
                "RAG_MAIN_MODEL=\"llama3\"\n\n"
                "# 2. RAG Embedding Model (Vectorization)\n"
                "RAG_EMBED_HOST=\"http://localhost:11434\"\n"
                "RAG_EMBED_MODEL=\"nomic-embed-text\""
             )
             console.print(Panel(example_text, title=".env Example", border_style="green", style="dim"))
        
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
