# FlowArchitect

**Diploma thesis** · HSE University, Faculty of Informatics, Mathematics and Computer Science, 2026  
**Author:** Makarov Dmitry · **Supervisor:** Babkin Eduard Alexandrovich

FlowArchitect is a PyQt6 desktop application for generating Apache NiFi ETL flows from natural-language descriptions. The main usage path is GUI-first: the user describes a pipeline in chat, reviews the intermediate YAML model, edits it if needed, and then converts it into NiFi JSON.

Research hypothesis: the two-stage pipeline `NL → YAML → NiFi JSON` reduces LLM hallucinations and improves structural correctness compared with direct `NL → JSON` generation.

---

## What The App Does

- accepts ETL requirements in a chat interface;
- generates a PIM model in YAML;
- converts YAML into NiFi JSON in multiple modes;
- lets the user inspect, edit, save, and import the result into NiFi;
- stores session history and basic generation statistics.

## GUI-First Workflow

1. The user describes the ETL task in chat.
2. The LLM produces a PIM model shown in the YAML editor.
3. The user adjusts YAML and fills placeholders if needed.
4. The app generates NiFi JSON via the adapter or an LLM mode.
5. The JSON can be saved or imported into NiFi from the UI.

## Generation Modes

| Mode | Path | Purpose |
|------|------|---------|
| `0 — Direct` | `NL → LLM → NiFi JSON` | single LLM call, highest hallucination risk |
| `1 — Adapter` | `NL → LLM → YAML → Adapter → NiFi JSON` | main mode, deterministic PIM→PSM conversion |
| `2 — LLM×2` | `NL → LLM → YAML → LLM → NiFi JSON` | flexible two-step generation |
| `3 — Adapter+LLM` | `NL → LLM → YAML → Adapter → LLM corrector` | adapter output with LLM-based JSON correction |

**PIM (Platform-Independent Model)** is a YAML description of sources, steps, sinks, and links.  
**PSM (Platform-Specific Model)** is the resulting NiFi JSON with processors, connections, UUIDs, and process groups.

---

## Application UI

- **Chat panel** for user requests and service messages.
- **Code editor** with `PIM — YAML` and `PSM — NiFi JSON` tabs.
- **History panel** with sessions, rename/delete actions, and basic stats.
- **Placeholder panel** for tracking unresolved `{{PLACEHOLDER}}` values.
- **Settings / Stage Providers** for LLM provider selection per pipeline stage.

## Architecture

```text
User request in chat
  → ChatController
  → EventBus
  → Orchestrator
  → LLM: NL → PIM
  → YAML shown in editor

Generate NiFi Flow action
  → EventBus
  → Orchestrator
  → YAML validation with Pydantic
  → Adapter or LLM
  → NiFi JSON shown in editor
  → optional import into NiFi
```

Components communicate through a thread-safe `EventBus` instead of direct service calls.

---

## Quick Start

### Requirements

- Python 3.11+
- at least one LLM API key;
- Apache NiFi is only required for import and integration testing.

### Installation

```powershell
git clone <repo-url>
cd FlowArchitect

python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Configuration

`config/api_presets.json` is already present in the repository. If you want a clean template, start from `config/api_presets.json.example` and fill in your provider keys and models.

Check `config/settings.json` if you want to preconfigure theme, active preset, or NiFi settings.

### Run The GUI

```powershell
python -m src.main
```

Typical usage:

1. Select a provider via `Provider` or `Settings`.
2. Enter the task in chat.
3. Review the generated YAML in the `PIM` tab.
4. Run the desired JSON generation mode.
5. Save the result or send it to NiFi with `→ NiFi`.

---

## Project Structure

```text
src/
  main.py                  # GUI entry point
  controllers/             # UI event handlers
  services/orchestrator.py # main MDA pipeline
  adapters/nifi_adapter.py # rule-based PIM → NiFi JSON
  domain/                  # Pydantic models for PIM and NiFi
  handlers/llm_engine.py   # LLM calls and provider routing
  ui/                      # PyQt6 interface

config/
  api_presets.json         # provider presets
  settings.json            # runtime settings
  prompts/                 # prompt templates
  PIM_structure.yaml       # sample intermediate model

tests/
  unit/                    # adapter unit tests
  integration/             # e2e and NiFi integration
  fixtures/                # ready-made PIM scenarios

scripts/
  run_adapter.py
  run_llm_fixture.py
  import_and_report.py
  full_pipeline.py
```

## Where To Start In Code

- `src/services/orchestrator.py` for the full NL → PIM → PSM flow.
- `src/adapters/nifi_adapter.py` for deterministic NiFi generation.
- `src/domain/pim_model.py` for the intermediate schema.
- `src/ui/main_window.py` for the main window layout.
- `src/ui/code_editor.py` for generation modes, tabs, and NiFi import.

---

## CLI Scripts

CLI support is secondary in this project. These scripts are mainly for adapter debugging, experiment replay, and integration checks without the GUI.

```powershell
# PIM JSON/YAML → NiFi JSON without an LLM
python scripts/run_adapter.py tests/fixtures/kafka_to_postgres.json

# Replay a saved LLM response
python scripts/run_llm_fixture.py --llm-response saved_llm_output.json --out result.json

# Import JSON into NiFi and save an error report
python scripts/import_and_report.py result.json --report errors.json

# Full fixture → adapter → import → report loop
python scripts/full_pipeline.py tests/fixtures/kafka_to_postgres.json --report errors.json
```

Detailed CLI workflow is documented in `docs/cli_testing.md`.

## Tests

```powershell
# unit tests without tokens or NiFi
pytest tests/unit/test_adapter_unit.py -v

# full test suite
pytest tests/ -v

# integration tests
$env:GEMINI_MODEL = "gemini-2.0-flash"
pytest tests/integration/ -v -s
```

Main scenarios: `currency-http-to-file`, `kafka-to-postgres`, `postgres-to-kafka`, `s3-to-hdfs`.

## Tech Stack

- Python 3.12
- PyQt6
- Pydantic 2
- PyYAML
- requests / openai SDK
- pytest

Supported providers include Google Gemini, OpenAI, Groq, and OpenAI-compatible endpoints.

## Research Context

The project formalizes and evaluates an MDE approach to Apache NiFi configuration generation. The key idea is to move semantic flow description into a smaller, editable YAML layer and handle NiFi JSON structural complexity separately.

Evaluation metrics:

- `PCT` — whether generated JSON imports into NiFi without errors;
- functional correctness of the resulting flow;
- effort reduction compared with manual configuration.

## License

Academic project for an HSE diploma thesis. Not intended for commercial use.
