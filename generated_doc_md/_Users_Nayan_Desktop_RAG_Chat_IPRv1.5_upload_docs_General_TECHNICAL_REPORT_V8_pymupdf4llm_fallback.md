# Technical Report: DevOps Agent
#### Bridging Natural Language and Infrastructure Orchestration

Nayan Modi

December 2025
## Table of Contents

Technical Report: DevOps Agent .................................................................................... 4

Bridging Natural Language and Infrastructure Orchestration ........................................ 4

Table of Contents ...................................................................................................... 4

1. Executive Summary & Problem Definition ................................................................ 5

1.1 Introduction ..................................................................................................... 5

1.2 The Core Problem: Cognitive Load and Friction ................................................... 5

1.3 The Solution: Semantic Middleware ................................................................... 6

2. Architectural Philosophy: The Agentic Approach ...................................................... 7

2.1 “Tools, not Rules” ............................................................................................. 7

2.2 The Hub-and-Spoke Model ................................................................................ 7

2.3 Privacy First (Local Execution) ........................................................................... 7

2.4 Richard Feynman’s “Explain it Simply” Rule ....................................................... 7

3. Fundamentals: Understanding the Building Blocks ................................................... 8

3.1 The LLM: The “Brain” ......................................................................................... 8

3.2 The AI Agent: The “Chef” ................................................................................... 8

3.3 The MCP (Model Context Protocol): The “Universal Plug” .................................... 8

3.4 The Synthesis: How They Connect in This Project ................................................ 9

4. Technology Stack Overview .................................................................................. 10

4.1 The Stack at a Glance...................................................................................... 10

4.2 Component Breakdown .................................................................................. 11

5. The Multi-MCP System Architecture ...................................................................... 12

5.1 Why Multi-MCP? ............................................................................................. 12

5.2 Diagram: The Federation of Servers .................................................................. 12

5.3 Server Deep Dive ............................................................................................ 13

5.4 Tool Registration & Discovery .......................................................................... 14

6. Cognitive Engine: The Dual-Agent “Split-Brain” System .......................................... 15


6.1 “System 1” vs. “System 2” Thinking ................................................................. 15

6.2 The Routing Logic ........................................................................................... 15

6.3 Logic Flow Diagram......................................................................................... 16

6.4 Self-Correction & DSPy ................................................................................... 17

7. Multi-Host Infrastructure ...................................................................................... 18

7.1 Multi-Host Architecture Diagram ..................................................................... 19

8. Session & Context Management ........................................................................... 20

8.1 How Sessions Work ........................................................................................ 20

8.2 Session Architecture Diagram ......................................................................... 21

8.3 Data Model .................................................................................................... 21

9. CLI Command Reference ..................................................................................... 22

9.1 Core Commands ............................................................................................ 22

9.2 Session Management ...................................................................................... 22

9.3 Server Management ........................................................................................ 22

9.4 CLI Hierarchy Diagram .................................................................................... 23

10. The Safety & Reliability Layer ............................................................................... 24

Tier 1: Input Checking (The Syntax Guard) .............................................................. 24

Tier 2: The Semantic Circuit Breaker (The Human Guard) ........................................ 24

Tier 3: Read-Only Mode (The Policy Guard) ............................................................. 26

11. Self-Healing & Debugging Intelligence ................................................................. 27

11.1 The Debugging Loop ...................................................................................... 27

11.2 Example: Fixing a Crash ................................................................................ 29

12. Complete Tool Reference & Supported Commands .............................................. 30

12.1 Docker Capabilities (Local)............................................................................ 30

12.2 Local Kubernetes Capabilities (Dev) ............................................................... 30

12.3 Remote Kubernetes Capabilities (Prod) .......................................................... 31

13. Remote Kubernetes: Practical Examples (CLI Style) .............................................. 32

13.1 Example 1: Listing Deployments .................................................................... 32

13.2 Example 2: Describing a Service .................................................................... 33

13.3 Example 3: Finding a Lost Pod ........................................................................ 34

14. Detailed Lifecycle of a Remote Kubernetes Command ......................................... 35

14.1 Phase 1: Ingestion & Intent Analysis ............................................................... 35

14.2 Phase 2: The Cognitive Loop (DSPy) ............................................................... 35


14.3 Phase 3: The First Execution (Search) ............................................................. 35

14.4 Phase 4: The Second Execution (Diagnosis) .................................................... 36

14.5 Phase 5: Deep Inspection .............................................................................. 36

14.6 Phase 6: Human Output ................................................................................ 36

14.7 Phase 7: End-to-End Data Flow Summary ....................................................... 37

15. Future Enhancements ........................................................................................ 38

15.1 Voice Interface (Star Trek Mode) .................................................................... 38

15.2 Predictive Healing ......................................................................................... 38

15.3 Multi-User Collaboration (Swarm Intelligence) ................................................ 38

15.4 Cloud Provider MCPs .................................................................................... 38

16. Conclusion ........................................................................................................ 39


## Technical Report: DevOps Agent
### Bridging Natural Language and Infrastructure Orchestration

**“An intelligent, secure, and extensible copilot that turns plain English into**
**precise DevOps actions, empowering engineers to manage Docker and**
**Kubernetes with unprecedented ease.”**

#### **Table of Contents**


Topic Page No.

**1. Executive Summary & Problem Definition** 2

**2. Architectural Philosophy: The Agentic Approach** 3

**3. Fundamentals: Understanding the Building Blocks** 5

**4. Technology Stack Overview** 7

**5. The Multi-MCP System Architecture** 8

**6. Cognitive Engine: The Dual-Agent “Split-Brain” System** 10

**7. Multi-Host Infrastructure** 12

**8. Session & Context Management** 13

**9. CLI Command Reference** 14

**10. The Safety & Reliability Layer** 15

**11. Self-Healing & Debugging Intelligence** 16

**12. Complete Tool Reference & Supported Commands** 17

**13. Remote Kubernetes: Practical Examples** 19

**14. Detailed Lifecycle of a Remote Kubernetes Command** 21

**15. Future Enhancements** 23

**16. Conclusion** 24


### 1. Executive Summary & Problem Definition
#### 1.1 Introduction

In the modern era of cloud-native computing, the complexity of infrastructure
management has exploded. Engineers operate in a mixed environment where they must
continually context-switch between local Docker containers, local Kubernetes testing
clusters (e.g., Minikube), and remote production clusters running on cloud providers like
AWS or GCP.


The **DevOps Agent** is a comprehensive solution designed to bridge the gap between
human intent and machine execution. It is not merely a “wrapper” for CLI commands; it is
a reasoning engine capable of understanding context, checking safety constraints, and
orchestrating actions across multiple isolated servers.

#### 1.2 The Core Problem: Cognitive Load and Friction


DevOps engineers act as translators.


They translate business requirements (“Restart the payment service”) into rigid,
syntactically unforgiving terminal commands:


( `kubectl rollout restart deployment/payments -n prod` ).


This translation process introduces significant friction:


1. **Syntax Recall** : The mental overhead of remembering flags and parameters for `docker`,
`kubectl`, `helm`, and custom scripts.


2. **Context Switching** : Moving between reading documentation, checking system status,
and executing commands breaks the “flow state”.


3. **Catastrophic Risk** : A minor typo in a powerful command (e.g., deleting the wrong
namespace) can cause significant downtime.


4. **Tool Silos** : Information is fragmented. To debug an issue, an engineer might need to run
`docker logs`, then `kubectl get pods`, then `ssh` into a node, manually correlating
timestamps and IDs.


#### 1.3 The Solution: Semantic Middleware

The DevOps Agent acts as an **Intelligent Layer** . It intercepts high-level human intent and
compiles it into low-level execution plans.


**Key capabilities include:**


**1)** **Natural Language Understanding (NLU)** : Parsing vague instructions like “My app is

crashing” into specific diagnostic actions.


**2)** **Context Retention** : Remembering that “the pod” refers to `frontend-7b56f`

mentioned three turns ago.


**3)** **Safety Guardrails** : Proactively detecting destructive intent and enforcing a human
in-the-loop confirmation step. * **Hybrid Execution** : Seamlessly interacting with
local processes and remote APIs within the same conversation string.


### 2. Architectural Philosophy: The Agentic Approach

To build a system that feels like a “Copilot” rather than a “Smart-Clip-Board.py,” we
adopted a specific set of architectural principles.

#### 2.1 Tools, not Rules


Traditional automation relies on scripts (Rules). If condition A happens, run script B. This is
brittle. Our agent uses **Tools** . We give the AI a toolbox (List Pods, Restart Log, Describe
Node) and a goal. The AI creates its own plan. If the first tool fails (e.g., “Pod not found”),
the AI can reason and try a different tool (e.g., “List all pods to find the correct name”).

#### 2.2 The Hub-and-Spoke Model


To ensure scalability and stability, the system uses a **Hub-and-Spoke** architecture. * **Hub** :
The Central Agent (Orchestrator). It handles cognition, history, and user interaction. *
**Spokes** : The MCP Servers. They handle the “dirty work” of talking to sockets, APIs, and file
systems.

#### 2.3 Privacy First (Local Execution)


Unlike many modern AI tools that rely on cloud APIs (OpenAI, Anthropic), the DevOps
Agent is designed to run **entirely locally** . * **Ollama** : We utilize Ollama to serve openweights models (Llama 3, Qwen 2.5) directly on the user’s hardware. * **Security** : Sensitive
infrastructure data (secrets, extensive logs, proprietary code names) never leaves the
user’s secure perimeter.

#### 2.4 Richard Feynman’s “Explain it Simply” Rule


The system is designed to be introspective. When it takes a complex action, it doesn’t just
display `Exit Code 0` . It explains _why_ it took that action and _what_ the result means in plain
English, much like the famous physicist Richard Feynman explaining complex physics
concepts.


### 3. Fundamentals: Understanding the Building Blocks

For readers unfamiliar with modern AI architecture, this section breaks down the core
components using simple analogies.

#### 3.1 The LLM: The “Brain”


A Large Language Model (LLM) is like a very well-read librarian who has read every book on
the internet but has no hands.


**What it does** : It understands language. It knows that “K8s” means “Kubernetes” and that
“restart” implies a sequence of stopping and starting.


**Limitation** : It cannot _do_ anything. It calculates words, not actions. It can write the
command `docker run`, but it cannot press Enter.

#### 3.2 The AI Agent: The “Chef”


An AI Agent is the software wrapper that gives the LLM a purpose and a process.


**Analogy** : Think of a Master Chef:


**1.** **Input** : “I want a spicy dinner.”


**2.** **Reasoning (LLM)** : “Spicy means chili peppers. Dinner means a main course.”


**3.** **Planning** : “I need to chop vegetables, boil water, and sauté the meat.”


**4.** **Acting (Tools)** : The Chef physically picks up a knife (Tool) and cuts the carrot.


**In our project** : The Agent wrapper tells the LLM:


_“You are a DevOps Engineer. Here is a list of tools you can use. Solve the user’s problem.”_

#### 3.3 The MCP (Model Context Protocol): The “Universal Plug”


Before MCP, connecting an AI to a tool was like hard-wiring a lamp directly into the wall. If
you wanted to move the lamp, you had to tear down the wall.


**MCP** is like a standard USB plug or a wall socket.


**Standardization** : It defines a universal language for how AI asks for things (“Call Tool X”)
and how tools reply (“Here is the Data”).


**Decoupling** : The AI (Agent) doesn’t need to know _how_ `list_pods` works. It just plugs into
the `K8s Socket` (MCP Server) and sends the request.


_Fig 1_

#### 3.4 The Synthesis: How They Connect in This Project


In the **DevOps Agent**, we combine these three:


**1.** **Ollama (LLM)** provides the raw intelligence.
**2.** **DSPy (Agent Framework)** guides the LLM to think step-by-step (System 2 thinking).
**3.** **MCP Servers** provide the hands to touch the Docker engine and Kubernetes API.


The result is a system where the “Brain” effectively controls the “Hands” through a safe,
standardized protocol, allowing you to control massive infrastructure with a sentence.


### 4. Technology Stack Overview

The DevOps Agent is built on a carefully selected stack of modern, production-grade
technologies. Each layer is chosen for a specific purpose.

#### 4.1 The Stack at a Glance


_Fig 2_


#### 4.2 Component Breakdown

Component Purpose Why We Chose It

**Python 3.11+** Core Language Type hints, asyncio, and a
massive ecosystem.

**Typer** CLI Framework Clean, type-safe commandline interfaces with minimal
boilerplate.

**DSPy** Agent Framework Enables structured, selfcorrecting LLM prompts.

**Ollama** LLM Runtime Run open-weight models
locally with a simple API.

**Werkzeug** WSGI Server Lightweight HTTP server for
hosting MCP endpoints.

**json-rpc** RPC Protocol Standard JSON-RPC 2.0
implementation for tool
invocation.

**Pydantic** Data Validation Strict input/output
validation for tool
arguments.

**docker-py** Docker SDK Native Python bindings to
the Docker daemon. No
shell commands.

**requests** HTTP Client Simple, reliable calls to the
Kubernetes API.


### 5. The Multi-MCP System Architecture

The backbone of the DevOps Agent is the **Model Context Protocol (MCP)** . We do not run a
single monolithic server. Instead, we orchestrate a **Federation of MCP Servers** .

#### 5.1 Why Multi-MCP?


Running single-program agents is dangerous. If the Docker client hangs, it shouldn’t freeze
the Kubernetes capabilities.


**Process Isolation** : Each server runs in its own OS process. A crash in the “Remote K8s”
server does not bring down the “Local Docker” server.


**Port Separation** : We utilize distinct ports for distinct domains (8080, 8081, 8082).


**Extensibility** : Adding a new domain (e.g., “AWS Manager”) is as simple as spinning up a
new server on port 8083; the main Agent code barely needs to change.

#### 5.2 Diagram: The Federation of Servers


_Fig 3_


#### 5.3 Server Deep Dive

_5.3.1 The Docker Server (Port 8080)_

  - **Responsibility** : Managing the local container runtime.

  - **Implementation** : Uses the official `docker-py` SDK. avoiding usage of shell

commands ( `subprocess.run('docker ...')` ) to prevent command injection
vulnerabilities.

  - **Key Tools** : `docker_list_containers`, `docker_start_container`, `docker_logs` .

_5.3.2 The Local K8s Server (Port 8081)_

  - **Responsibility** : Managing development clusters (Docker Desktop, Kind, Minikube).

  - **Implementation** : It intelligently manages a background `kubectl proxy` process to

create a secure, authenticated tunnel to the cluster’s API server. This allows us to
make clean REST API calls to `127.0.0.1:8001` instead of parsing messy CLI output.

_5.3.3 The Remote K8s Server (Port 8082)_




- **Responsibility** : Managing production/staging clusters.

- **Complexity** : This server handles authentication (Kubeconfig contexts), network

latency issues, and large dataset pagination (listing 10,000 pods).

- **Key Capabilities** : It includes advanced “Describe” tools that aggregate events,

status, and logs into a single coherent summary, saving the user from running 3-4
separate inspection commands.


#### 5.4 Tool Registration & Discovery

The system uses a **dynamic Tool Registry** . Tools are not hard-coded into the agent, they
are discovered at startup.


_Fig 4_


This design allows new tools to be added simply by:


1. Creating a new Python class that inherits from `Tool` .


2. Defining a `name`, `description`, and `get_parameters_schema()` method.


3. Importing it into the `__init__.py` of the relevant tools module.


No changes to the agent’s core logic are required. The LLM learns about the new tool
automatically on the next startup.


### 6. Cognitive Engine: The Dual-Agent “Split-Brain” System

A major challenge in AI engineering is the trade-off between **Speed** and **Intelligence** .


A small model (1B params) is fast but stupid.


A large model (70B params) is smart but slow and creates massive latency.


The DevOps Agent solves this with a **“Split-Brain” Architecture**, featuring two distinct
agents working in tandem.

#### 6.1 “System 1” vs. “System 2” Thinking


Inspired by Daniel Kahneman’s _Thinking, Fast and Slow_ :


**System 1 (Fast Agent)** : Intuitive, instant, low-energy. Handles routine tasks.


**System 2 (Smart Agent)** : Deliberate, analytical, high-energy. Handles novel or complex
problems.

#### 6.2 The Routing Logic


When a user submits a query, the system makes a routing decision (currently heuristicbased, but can be moved towards classifier-based).


_Path A: The Fast Agent (The Reflex)_

  - **Model** : ~3B Parameters (e.g., `llama3.2:3b` ) or even `1.5b` .

  - **Prompt Engineering** : Heavily optimized for purely structural JSON output. Zero

“Chain of Thought”.

  - **Latency** : < 500ms.

  - **Use Case** : “List containers”, “Start nginx”, “Get logs for app”.

  - **Architecture** : > User Query -> Fast Model -> JSON -> Validation -> Execution

_Path B: The Smart Agent (The Professor)_




- **Model** : ~14B to 70B Parameters (e.g., `qwen2.5:32b`, `llama3.1:70b` ).

- **Prompt Engineering** : Uses **ReAct** (Reasoning + Acting) and **CoT** (Chain of Thought).

- **Latency** : 3-10 seconds.

- **Use Case** : “Why is my payment service crashing?”, “Debug the latency in the



remote cluster”, “Clean up all unused images and stopped containers”.

- **Architecture** : > User Query -> Smart Model -> Thought Process -> Plan -> JSON ->



Validation -> Execution


#### 6.3 Logic Flow Diagram



_Fig 5_


#### 6.4 Self-Correction & DSPy

We use **DSPy** (Declarative Self-improving Python) to manage these interactions. A key
feature is the **Self-Correction Loop** . If the “Fast Agent” hallucinates a tool argument (e.g.,
`docker_run(image="nginx", speedy=True)` where `speedy` is not a valid arg), the Validator
catches this exception.


Instead of failing, the system:


1. Captures the error: `TypeError: unexpected keyword argument 'speedy'` .


2. Feeds it back to the **Smart Agent** .


3. The Smart Agent “reads” the error and retries the generation with the correct schema.


### 7. Multi-Host Infrastructure

In a real-world enterprise environment, you cannot always run a massive 70B parameter
model on a developer’s laptop. It requires ~48GB of VRAM. However, developers love the
low latency of running small models locally.


To solve this, the DevOps Agent supports a **hybrid Multi-Host** configuration.


**The “Hot-Swap” Capability** The architecture decouples the _Agent Logic_ from the _LLM_
_Compute_ . You can configure the system such that:


**1. Fast Agent** runs on `localhost`


(using `llama3.2:3b` on the laptop’s NPU/GPU).


**2.** **Smart Agent** runs on a `Remote Server`


(e.g., a shared DGX station or High-Performance Computing cluster) running `llama3.1:70b` .


**Configuration Code Snippet** The system uses Pydantic Settings to manage this
seamlessly.


#### 7.1 Multi-Host Architecture Diagram

This diagram illustrates how a single agent instance can dispatch requests to multiple
Ollama hosts.


_Fig 6_


### 8. Session & Context Management

A key challenge when building an AI assistant is **memory** . Without it, every command is
answered in isolation. “Show me the pods” followed by “Restart the first one” would fail
because the agent forgot which pods it just listed.


The DevOps Agent solves this with a **SQLite-backed Session Management System** .

#### 8.1 How Sessions Work

**1.** **Create Session** : User starts a named session

(e.g., `devops-agent session start "Debug Auth"` )

**2.** **Persist Context** : Every query and response is saved to a local SQLite database.


**3.** **Resume Session** : The user can resume a session later, and the agent has full

memory of the conversation.

**4.** **End Session** : User explicitly ends the session when done.


#### 8.2 Session Architecture Diagram 8.3 Data Model

The database stores two primary entities:


**1. Sessions** : `id`, `title`, `created_at`



_Fig 7_



**2.** **Messages** : `session_id`, `role` (user/assistant), `content`, `timestamp`


This allows the system to:


1) List all past sessions.


2) Show the full conversation log for any session.


3) Clear sessions to free up space.


### 9. CLI Command Reference

The DevOps Agent is controlled via a rich command-line interface built with **Typer** . Here is
a summary of all available commands.

#### 9.1 Core Commands

Command Description

`devops-agent run "<query>"` Execute a single natural language query.

`devops-agent chat` Start an interactive REPL (Read-Eval-Print
Loop) session.

`devops-agent list-tools` Display all available Docker and Kubernetes
tools.

#### 9.2 Session Management

Command Description

`devops-agent session start "<title>"` Create a new named session and set it as
active.

`devops-agent session end` End the current active session.

`devops-agent session list` List all saved sessions.

`devops-agent session show <id>` Display the conversation log for a specific
session.

`devops-agent session clear [id]` Delete a specific session or all sessions.

#### 9.3 Server Management

Command Description

`devops-agent start-server` Start the Docker MCP server (port 8080).

`devops-agent start-k8s-server` Start the Local K8s MCP server (port 8081).

`devops-agent start-remote-k8s-server` Start the Remote K8s MCP server (port
8082).

`devops-agent start-all` Interactive wizard to start all 3 servers.


#### 9.4 CLI Hierarchy Diagram



_Fig 8_


### 10. The Safety & Reliability Layer

Allowing an AI to control infrastructure is inherently risky. “What if it deletes my database?”
is the first question every engineer asks. We address this with a 3-Tier Safety Layer.

#### Tier 1: Input Checking (The Syntax Guard)


Before any tool is called, the arguments are validated against strict Pydantic models.


If a tool expects an `integer` port and the AI sends a `string`, it is rejected.


If a tool requires a `namespace` and the AI forgets it, it is rejected.

#### Tier 2: The Semantic Circuit Breaker (The Human Guard)


We maintain a registry of `DANGEROUS_TOOLS` .


- **Safe** : `list_pods`, `describe_node`, `get_logs` .


- **Dangerous** : `delete_pod`, `scale_deployment`, `docker_stop` .


When a Dangerous Tool is selected:


1) Execution is **Paused** .


2) The User is presented with an **Impact Analysis** .


3) The User must explicitly type **`YES`** or **`CONFIRM`** to proceed.


Fig. 9


#### Tier 3: Read-Only Mode (The Policy Guard)

The system can be started in a strictly `read-only` mode.


In this mode, the `DANGEROUS_TOOLS` are completely removed from the prompt context.


The AI _literally doesn’t know_ that it has the ability to delete things.


This is perfect for junior engineers who need to debug prod without risk of breaking it.


### 11. Self-Healing & Debugging Intelligence

One of the most powerful features of the DevOps Agent is its ability to understand **failure** .


When a standard CLI command fails, it spits out an error code: `Error: Exit Code 137` .


The user has to Google/StackOverflow this or ask ChatGPT or ask other LLMs chats.
But when our DevOps Agent sees an error, it enters **Analysis Mode** .

#### 11.1 The Debugging Loop



**1.** **Detection** : The MCP Server catches the exception (e.g., `Kubernetes 403`

`Forbidden` ).
**2.** **Enrichment** : The Server adds context. It doesn’t just say “Forbidden”. It says

“Forbidden: Service Account ‘default’ does not have ‘list’ access on ‘pods’”.
**3.** **Explanation** : The Agent receives this error and uses the LLM to translate it.




`o` _Raw Error_ : `CrashLoopBackOff`

`o` _Agent Explanation_ : “The pod started but immediately died. This usually



happens when the application panics or a configuration file is missing.”
**4.** **Prescription/Fix suggestion** : The Agent suggests the next step: _“I recommend_



_capturing the logs of the previous instance to see the panic message.”_


_Fig. 10_


#### 11.2 Example: Fixing a Crash

**User** : “Why is my database container dying?”

**Agent** : “The container `db-prod` exited with code 1. Let me check the logs.” _(Agent_
_runs_ _`docker_logs`_ _)_

**Agent** : “The logs show `FATAL: password authentication failed for user`
`'postgres'` . It seems your environment variable `POSTGRES_PASSWORD` does not
match the config. Please check your `.env` file.”


This capability transforms the tool from an “Executor” into a “Analyst” that sits beside you.


### 12. Complete Tool Reference & Supported Commands

This section lists the comprehensive inventory of skills currently available to the Agent.

#### 12.1 Docker Capabilities (Local)


These tools interact with the Docker Daemon on your local machine via the Docker Socket.


Tool Name Description

`docker_list_containers` List all running or stopped containers. Filter
by name/status.

`docker_run_container` Start a new container. Supports port
mapping, env vars, and detach mode.

`docker_stop_container` Gracefully stop a running container.
( **Dangerous** : Requires confirmation)

`docker_logs` Fetch stdout/stderr logs from a container.

#### 12.2 Local Kubernetes Capabilities (Dev)


These tools interact with local clusters like Docker Desktop, Kind, or Minikube via `kubectl`
`proxy` .


Tool Name Description

`local_k8s_list_pods` List pods in the default or specified
namespace on localhost.

`local_k8s_list_nodes` Show the status of nodes in the local
development cluster.


#### 12.3 Remote Kubernetes Capabilities (Prod)

These tools are optimized for remote, high-latency interactions with production clusters
(EKS, GKE, AKS).


Tool Name Description Key Feature


```
remote_k8s_list_namespac
es
remote_k8s_find_pod_name
space

remote_k8s_get_resources
_ips

remote_k8s_list_deployme
nts

remote_k8s_describe_depl
oyment

```


List all namespaces. Status & Age tracking.



Detailed manifest
inspection.



Search for a pod across ALL
namespaces.

Get internal/external IPs for
Pods/Nodes.



“Where is `my-app` ?”


Fast networking lookups.



List Deployment resources. Shows Replicas
(Desired/Ready).



`remote_k8s_describe_node` Deep node inspection
(Memory/CPU).

`remote_k8s_describe_pod` Deep diagnostics for failing
pods.



Shows Strategy &
Conditions.

Shows Taints & Pressure.


**Auto-fetches Events &**
**Logs.**



Shows ClusterIPs & Ports.


```
remote_k8s_describe_name
space

```


Metadata and quotas for
namespaces.



`remote_k8s_list_services` List all Services
(Internal/LoadBalancer).



`remote_k8s_get_service` specific Service details. Shows Selector &
Endpoints.



Troubleshooting
connectivity.


```
remote_k8s_describe_serv
ice

```


Deep service inspection +
Events.


### 13. Remote Kubernetes: Practical Examples (CLI Style)

Examples for of how the Agent interacts with the Remote K8s MCP, showing the exact input
and output.

#### 13.1 Example 1: Listing Deployments


**Goal** : Check the state of applications in the `prod` namespace.


**Input** :

```
devops-agent run "List all deployments in the prod namespace"

```

**Output** :

```
>  Connectng to Remote Cluster...
>  Agent Mode: Fast (System 1)
>  Tool Selected: remote_k8s_list_deployments(namespace='prod')

 SUCCESS: Found 3 deployments in 'prod'

NAME       REPLICAS  READY  UPDATED  AGE
--------------- --------  -----  -------  --payment-service 3     3    3     14d
frontend-web   5     5    5     2d
worker-queue   2     1    2     5h

 Notice: 'worker-queue' has only 1/2 ready replicas.

```

#### 13.2 Example 2: Describing a Service

**Goal** : Find the LoadBalancer IP for an external service.


**Input** :

```
devops-agent run "Get details for the ingress-gateway service"

```

**Output** :

```
>  Connectng to Remote Cluster...
>  Agent Mode: Smart (System 2)
>  Thought: User requested service details. I will use 'get_service'.

--------------------------------------------------SERVICE: ingress-gateway
NAMESPACE: default
TYPE: LoadBalancer
--------------------------------------------------CLUSTER-IP:  10.96.14.22
EXTERNAL-IP:  34.12.45.99 <-- Access here
PORTS:     80:31234/TCP, 443:32111/TCP

SELECTORS:   app=ingress, component=router
ENDPOINTS:   10.244.1.5, 10.244.2.8
--------------------------------------------------
```

#### 13.3 Example 3: Finding a Lost Pod

**Goal** : Locate a pod when you don’t know the namespace.


**Input** :

```
devops-agent run "Where is the redis-cache pod running?"

```

**Output** :

```
>  Connectng to Remote Cluster...
>  Agent Mode: Smart (System 2)
>  Thought: User didn't specify namespace. I'll use the 'find_pod' tool to
search globally.
>  Tool Selected: remote_k8s_find_pod_namespace(pod_names=['redis-cache'])

 SEARCH RESULTS
----------------Pod Name:   redis-cache
Found In:   [ 'backend-db', 'staging-db' ]

 The pod exists in multiple namespaces.
- backend-db (Active)
- staging-db (Terminating)

Which one would you like to inspect?

```

### 14. Detailed Lifecycle of a Remote Kubernetes Command

To truly understand the system, we will trace the exact lifecycle of a complex command
interacting with the **Remote Kubernetes MCP** .


**User Query** : `"Describe the pod 'backend-worker-x9z' in the remote cluster and`
```
tell me why it failed"

#### 14.1 Phase 1: Ingestion & Intent Analysis

```


**1.** **CLI receives input** : The user presses Enter.
**2.** **State Injection** : The Agent quickly polls the active context. It sees a session is



active.
**3.** **Routing** : The Complexity Analyzer sees words like “why it failed” and “remote”. It



knows this requires reasoning (diagnostics) and specific routing (remote). It selects
the **Smart Agent** .


#### 14.2 Phase 2: The Cognitive Loop (DSPy)

The Smart Agent (70B Model) begins its Chain of Thought:


**1.** _**Thought**_ : “The user wants to diagnose a pod. I need to find the pod first. The user
specified ‘remote cluster’. I should use the `remote_k8s` toolset.”


**2.** _**Reasoning**_ : “I cannot describe it if I don’t know the namespace. I will first search for the
pod, then describe it.”


**3.** _**Plan**_ : Call `remote_k8s_list_pods` to find the namespace.


**Tool Call 1 (Internal)** :

```
{ "tool" : "remote_k8s_list_pods", "args" : { "all_namespaces" : true } }

#### 14.3 Phase 3: The First Execution (Search)
```

**1.** **Routing** :

     - The MCP router sees `remote_k8s_` .

     - It directs the JSON-RPC call to `http://localhost:8082` .


**2.** **Server Action** :

     - The Remote K8s Server receives the call.

     - It uses the `kubernetes` Python client to query the Cloud API.


**3.** **Result** :

     - It returns a list of 50 pods.

     - The Agent parses this and finds `backend-worker-x9z` is in `prod-namespace` .


#### 14.4 Phase 4: The Second Execution (Diagnosis)

The Agent resumes reasoning:


**1)** _**Thought**_ : “Found it. It’s in `prod-namespace` . Now I can describe it to see the failure.”


**2)** _**Tool Selection**_ : `remote_k8s_describe_pod` .


**Tool Call 2 (Final)** :

#### 14.5 Phase 5: Deep Inspection

**1.** **Server Action** : The Remote Server executes the Describe logic.
**2.** **Data Aggregation** : It fetches:

`o` Pod Status ( `CrashLoopBackOff` )

`o` Container Exit Code ( `137`    - OOMKilled)

`o` Last 20 log lines (showing `Java Heap Space Error` )

`o` Events (showing `Preempted by scheduler` )
**3.** **Synthesis** : The server compiles this into a structured Markdown block.
#### 14.6 Phase 6: Human Output


The Agent presents the final analysis to the user:


- **Pod Analysis: backend-worker-x9z**


- **Cluster** : Remote


- **Status** : CrashLoopBackOff


- **Cause** : The process was killed (OOMKilled). The logs indicate a Java Heap Space error.


- **Event** : The node was under memory pressure.


#### 14.7 Phase 7: End-to-End Data Flow Summary

This diagram summarizes the complete journey of a user’s request.


_Fig 11_


### 15. Future Enhancements

The current system has established a solid foundation, but the potential for growth is
immense. Here is the roadmap for the next evolution of the DevOps Agent.

#### 15.1 Voice Interface (Star Trek Mode)


Integrating OpenAI **Whisper** (running locally) will allow engineers to walk into a server
room and verbally ask: _“Agent, what is the status of Rack 4?”_ or _“Read me the last error log.”_
This hands-free mode is critical for on-site hardware debugging.

#### 15.2 Predictive Healing


Currently, the agent is **Reactive** (it waits for a user command).


The future state is **Proactive** . The agent will run as a daemon, watching logs in the
background:


_**Scenario**_ **:** The Agent notices disk space filling up on `node-01` .


_**Action**_ **:** It proactively pings the user: _“Warning: Node-01 is at 95% disk usage. Shall I clear_
_the docker cache to free 10GB?”_

#### 15.3 Multi-User Collaboration (Swarm Intelligence)


Right now, the context is local. We plan to add a **Shared Context DB** .


_**Scenario**_ **:** User A asks “Debug the SQL pod”. User B joins the session and asks “What did
you find?”.


_**Action**_ **:** The Agent shares the context from User A’s session, enabling true team-based
debugging.

#### 15.4 Cloud Provider MCPs


Expanding beyond Docker and K8s to include **AWS, Azure, and GCP** MCPs.


_**Command**_ **:** “Provision a new S3 bucket and give the current pod access to it.”


_**Mechanism**_ **:** The Agent generates the Terraform code or uses `boto3` to apply the
infrastructure change instantly.


### 16. Conclusion

The **DevOps Agent** project represents a paradigm shift in how we interact with technology.


Definitions revisited:


  - We took the **Brain** (LLM) and taught it to understand infrastructure.


  - We gave it **Hands** (MCP Servers) to touch the servers safely.


  - We trained it to contain a **Chef’s Mindset** (AI Agent) to plan recipes for success.


By combining the **reasoning capabilities** of modern LLMs with the **structured safety** of
the Model Context Protocol, we have moved beyond simple “Chatbots” to true **Agentic**
**Systems** .


We have built a system that:


**1.** **Lowers the barrier to entry** for junior DevOps engineers.


**2.** **Increases speed and reduces errors** for senior engineers.


**3.** **Proves that AI can be secure, reliable, and has potential to be incredibly useful** in
critical infrastructure environments.


