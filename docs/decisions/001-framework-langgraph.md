# ADR 001: LangGraph over Google ADK

Status: accepted (Day 2 decision).

| Criterion | LangGraph | Google ADK | Winner |
|---|---|---|---|
| Graph/state control, recovery | Explicit typed state, conditional edges, reducers | Agent-centric; workflow agents exist but state is less explicit | LangGraph |
| Parallel calls + join | Static fan-out edges, join waits for all branches | Parallel agents supported | tie |
| Streaming progress | `astream(stream_mode=["updates","values"])` gives real per-node events | Event stream available | tie |
| Checkpointing / resume | Built-in checkpointers (not yet wired here) | Session services | LangGraph |
| Model-provider flexibility | Provider-agnostic (we use our own adapter + Ollama) | Strongest with Gemini/Vertex | LangGraph |
| Testability | Nodes are plain async functions taking (state, deps) | Good | tie |

Decision: LangGraph. Nodes are plain functions, so they are unit-testable without the framework, and the fan-out/join
and the needs_input early exit are explicit edges rather than prompt behaviour.
Trade-off: no Google-native tool integrations; acceptable because every tool sits behind our own provider interfaces.
