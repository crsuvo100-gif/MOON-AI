# app/

Core application package — the brain of MOON-AI. Contains ~150 modules:

- **brain/** — orchestrator, planner, aggregator (agent brain)
- **agents/** — 41 persona agents (advanced/professional/specialist)
- **memory/** — vector-DB memory system (episodic, semantic, procedural)
- **services/** — LLM & embedding services
- **connector/** — gateway/API connectors
- **sandbox/** — execution sandbox (filesystem, process, policies)
- **runtime/** — agent router, event bus, skill system
- **orchestrator/** — goal manager, planner, router, task analyzer
- **api/** — FastAPI + Flask API endpoints
- **terminal/** — VS Code terminal backend
- **execution/** — execution engine
- **improvement/** — self-improvement engine
- **evaluation/** — evaluation & benchmarks
- **context/** — context management
- **security/** — authorization & permission engine
- **models/** — data models
- **capability/** — capability manager & tool registry
- **knowledge/** — knowledge graph
- **skills/** — skill system
- **prompts/** — prompt templates
- **logs/** — runtime logs
- **config/** — configuration
- **core/** — core utilities

All modules use `snake_case` naming. Imports use `from app.brain.orchestrator import Orchestrator`.
