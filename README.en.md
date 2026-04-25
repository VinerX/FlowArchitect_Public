# FlowArchitect

**Diploma thesis** · HSE, Faculty of Informatics, Mathematics and Computer Science, 2026  
**Author:** Makarov Dmitry · **Supervisor:** Babkin Eduard Alexandrovich

---

## Overview

FlowArchitect automates the creation of [Apache NiFi](https://nifi.apache.org/) ETL pipeline configurations from natural language descriptions using LLMs and Model-Driven Engineering (MDE).

**Research hypothesis:** A two-stage approach (NL → YAML → NiFi JSON) produces fewer LLM hallucinations and better structural integrity than single-step direct generation (NL → JSON), because the intermediate YAML (Platform-Independent Model) separates semantic reasoning from structural complexity.

---

## The MDA Pipeline

Three generation modes are implemented and evaluated:

| Mode | Path | Description |
|------|------|-------------|
| **0 — Direct** | NL → LLM → NiFi JSON | Single call; highest hallucination risk |
| **1 — Adapter** | NL → LLM → YAML → Rule-based adapter → NiFi JSON | Default mode; deterministic PIM→PSM conversion |
| **2 — LLM-to-LLM** | NL → LLM → YAML → LLM → NiFi JSON | Two LLM calls; most flexible |

**PIM (Platform-Independent Model):** YAML describing the pipeline abstractly — sources, processing steps, sinks, and links.  
**PSM (Platform-Specific Model):** Apache NiFi JSON — processors, connections, UUIDs, process groups.

---

## Architecture

```
User Input (Chat)
  → ChatController → EventBus → Orchestrator
      → LLM (stage 1): NL → PIM (structured JSON/YAML)
      → Display YAML in editor

User clicks "Generate NiFi Flow"
  → EventBus → Orchestrator
      → Parse & validate YAML with Pydantic
      → NiFiAdapter.convert(Flow) → NiFi JSON   [Mode 1]
      → (or) LLM call → NiFi JSON               [Mode 2]
      → Display JSON in editor
```

All components communicate through a thread-safe `EventBus` (weak-reference subscriber pattern). Controllers never call services directly.

---

## Project Structure

```
FlowArchitect/
├── src/
│   ├── main.py                     # Entry point
│   ├── adapters/
│   │   └── nifi_adapter.py         # PIM → NiFi JSON (rule-based, auto-layout)
│   ├── controllers/                # MVC: UI event handlers
│   ├── core/
│   │   ├── events.py               # Thread-safe EventBus
│   │   └── event_defines.py        # Event name constants
│   ├── domain/
│   │   ├── pim_model.py            # Pydantic PIM schema (Flow, Resource, Step, Link)
│   │   └── nifi_schema.py          # Pydantic NiFi schema
│   ├── handlers/
│   │   └── llm_engine.py           # LLM orchestration + provider routing
│   ├── services/
│   │   └── orchestrator.py         # Main MDA pipeline
│   └── ui/                         # PyQt6 desktop GUI
├── config/
│   ├── api_presets.json.example    # Provider config template (copy & fill keys)
│   ├── settings.json               # Runtime settings (theme, active preset)
│   ├── PIM_structure.yaml          # Reference PIM schema example
│   └── prompts/                    # LLM prompt templates
│       ├── system_architect.txt    # NL → PIM generation prompt
│       └── psm_nifi.txt            # YAML → NiFi (Mode 2) prompt
├── tests/
│   ├── unit/                       # Adapter unit tests (no API/NiFi needed)
│   ├── integration/                # E2E tests (requires Gemini API + NiFi)
│   └── fixtures/                   # PIM JSON fixtures for 4 ETL scenarios
├── scripts/
│   ├── run_adapter.py              # PIM → NiFi JSON (no LLM)
│   ├── run_nl_test.py              # Full NL → NiFi test run
│   ├── import_and_report.py        # Import to NiFi + capture validation errors
│   └── full_pipeline.py            # PIM → adapter → import → report (one command)
└── requirements.txt
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- Apache NiFi 1.x or 2.x instance (for import tests only)
- At least one LLM API key (Gemini, OpenAI, Groq, or any OpenAI-compatible endpoint)

### Installation

```bash
git clone <repo-url>
cd FlowArchitect

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

pip install -r requirements.txt
```

### Configuration

```bash
# Copy the example config and fill in your API keys
cp config/api_presets.json.example config/api_presets.json
# Edit config/api_presets.json — add your key(s)
```

### Run the application

```bash
cd src
python main.py
```

---

## CLI Debug Tools (no GUI required)

```bash
# PIM YAML/JSON → NiFi JSON  (no LLM, no NiFi instance needed)
python scripts/run_adapter.py tests/fixtures/kafka_to_postgres.json

# Full automated test: NL description → NiFi import
python scripts/run_nl_test.py --preset "Google" --case kafka-to-postgres

# Import NiFi JSON into a running NiFi, capture validation errors
python scripts/import_and_report.py result.json --report errors.json

# Full loop: PIM fixture → adapter → NiFi import → error report
python scripts/full_pipeline.py tests/fixtures/kafka_to_postgres.json --report errors.json
```

NiFi credentials are read from environment variables only:

```bash
export NIFI_URL=https://localhost:8443
export NIFI_USER=admin
export NIFI_PASS=password
```

---

## Running Tests

```bash
# Unit tests — no tokens, no NiFi needed
pytest tests/unit/ -v

# All tests
pytest tests/ -v

# E2E integration (requires live Gemini API + running NiFi)
set GEMINI_MODEL=gemini-2.0-flash    # Windows
pytest tests/integration/ -v -s
```

**Test scenarios:**

| Case | Description |
|------|-------------|
| `currency-http-to-file` | REST API → file |
| `kafka-to-postgres` | Kafka → PostgreSQL |
| `postgres-to-kafka` | PostgreSQL → Kafka |
| `s3-to-hdfs` | S3 → HDFS |

Integration tests auto-skip when NiFi or the LLM API is unavailable.

---

## Evaluation Metrics

| Metric | Description |
|--------|-------------|
| **PCT** (Platform Conformance Test) | Does generated JSON import into NiFi without errors? |
| **Functional Correctness** | Does the imported flow execute the ETL task correctly? |
| **Effort Reduction** | Time to deploy with generator vs. manual configuration |

---

## Tech Stack

- **Python 3**, **PyQt6** — desktop GUI
- **Pydantic** — strict schema validation for PIM and NiFi models
- **PyYAML** — PIM serialization
- **requests / openai SDK** — LLM API calls (no heavy frameworks, for thesis transparency)
- **pytest** — unit + integration tests
- Supported LLM providers: Google Gemini, OpenAI, Groq, Mistral, any OpenAI-compatible endpoint

---

## License

Academic project — HSE diploma thesis, 2026. Not licensed for commercial use.
