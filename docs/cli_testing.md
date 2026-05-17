# CLI Testing Guide

This file is the operational playbook for running FlowArchitect experiments from the command line.
Keep generated experiment artifacts under `test_runs/`, not in the repository root.

For multi-case reproducible campaigns, use `scripts/run_campaign.py` together with
`config/campaigns/thesis_global_validation_template.yaml`. The campaign runner
executes runs sequentially, stores artifacts under `test_runs/campaigns/`, and
lets the operator or agent attach notes/status changes to individual runs.

## Main Runner

Use [scripts/run_nl_test.py](../scripts/run_nl_test.py) for model experiments. It runs the same backend path as the GUI:

```text
USER_QUERY -> Orchestrator -> PIM YAML -> REQUEST_CONVERSION -> NiFi JSON -> optional NiFi import
```

Campaign orchestration sits one level above this runner:

```powershell
.\.venv\Scripts\python.exe scripts\run_campaign.py template `
  --out config\campaigns\my_campaign.yaml

.\.venv\Scripts\python.exe scripts\run_campaign.py init `
  --manifest config\campaigns\my_campaign.yaml

.\.venv\Scripts\python.exe scripts\run_campaign.py run `
  --campaign my-campaign-id

.\.venv\Scripts\python.exe scripts\run_campaign.py sync `
  --campaign my-campaign-id `
  --manifest config\campaigns\my_campaign.yaml

.\.venv\Scripts\python.exe scripts\run_campaign.py materialize `
  --campaign my-campaign-id `
  --run-id <run-id>
```

Basic run:

```powershell
.\.venv\Scripts\python.exe scripts\run_nl_test.py `
  --query "Получай курс валют с сайта https://api.exchangerate.host/latest и записывай результат в файл rates.json" `
  --preset "openrouter qwen/qwen3.6-plus" `
  --mode 3 `
  --timeout 300
```

Full run with NiFi import:

```powershell
$s = Get-Content src\config\settings.json -Raw | ConvertFrom-Json
$env:NIFI_URL = $s.nifi_url
$env:NIFI_USER = $s.nifi_username
$env:NIFI_PASS = $s.nifi_password

.\.venv\Scripts\python.exe scripts\run_nl_test.py `
  --query "Получай курс валют с сайта https://api.exchangerate.host/latest и записывай результат в файл rates.json" `
  --preset "openrouter qwen/qwen3.6-plus" `
  --mode 3 `
  --pim-preset "openrouter qwen/qwen3.6-plus" `
  --corrector-preset 1003 `
  --timeout 300 `
  --nifi
```

If a broken local proxy is set, clear it for the test command:

```powershell
$env:HTTP_PROXY=''
$env:HTTPS_PROXY=''
$env:ALL_PROXY=''
$env:http_proxy=''
$env:https_proxy=''
$env:all_proxy=''
```

The observed failure mode was `127.0.0.1:9` refusing proxy connections while the actual target was correct (`openrouter.ai`).

## Modes

| Mode | Meaning | Path |
| --- | --- | --- |
| `0` | Direct | NL -> LLM -> NiFi JSON |
| `1` | Adapter | NL -> LLM -> PIM YAML -> NiFiAdapter -> NiFi JSON |
| `2` | LLM-to-LLM | NL -> LLM -> PIM YAML -> LLM -> NiFi JSON |
| `3` | Adapter + LLM corrector | NL -> LLM -> PIM YAML -> NiFiAdapter -> LLM semantic correction -> NiFi JSON |

For thesis experiments, mode `3` is the main high-signal path when comparing generated flows with NiFi import validation.

## Stage Providers

The runner supports separate providers for pipeline stages:

```powershell
--pim-preset "openrouter qwen/qwen3.6-plus"
--psm-preset 1002
--corrector-preset 1003
```

Stage mapping:

- `--preset`: base/default provider for the run.
- `--pim-preset`: provider for NL -> PIM generation.
- `--psm-preset`: provider for YAML -> JSON in mode `2`.
- `--corrector-preset`: provider for PIM correction and NiFi JSON correction.

Known useful local setup:

- `1000`: `openrouter qwen/qwen3.6-plus`, API provider via OpenRouter.
- `1001`: `Local`, local endpoint at `127.0.0.1:1234`, not the OpenRouter Qwen API.
- `1003`: `google/gemini-2.5-flash-lite` through OpenRouter, useful as a corrector.

Check current presets:

```powershell
.\.venv\Scripts\python.exe scripts\list_presets.py
```

## NiFi Import Behavior

By default, `--nifi` replaces an existing root-level process group when the generated flow name matches.
This keeps repeated tests from leaving many duplicate groups on the canvas.

Default behavior:

```powershell
--nifi
```

Legacy behavior, always create a new process group:

```powershell
--nifi --nifi-keep-existing
```

The GUI setting is `nifi_replace_existing_by_name`, default `true`.

## NiFi Archive Warning

Warning:

```text
Unable to write flowfile content to content repository container default due to archive file size constraints; waiting for archive cleanup.
```

This is a NiFi content repository/archive pressure issue, not a generator JSON issue.
For a test NiFi instance, stop NiFi and set:

```properties
nifi.content.repository.archive.enabled=false
```

Alternative test settings if archive must remain enabled:

```properties
nifi.content.repository.archive.max.retention.period=1 min
nifi.content.repository.archive.max.usage.percentage=5%
```

Do not delete content repository data on a production NiFi. For local disposable test instances, cleaning content/archive directories while NiFi is stopped is acceptable.

## Report Layout

Automatic report path when `--report` is omitted:

```text
test_runs/
  <model-slug>/
    mode-<0|1|2|3>/
      <test-case-slug>/
        <timestamp>.json
```

If `--report some_name.json` is passed without a directory, the runner writes to:

```text
test_runs/manual/some_name.json
```

Old root-level reports are archived under:

```text
test_runs/archive/
```

Do not add new `test_report*.json` or `test_result*.json` files to the repository root.

## Report Analytics

Each report includes:

- `query`, `mode`, `mode_name`
- selected `preset_id`, `preset_name`, `preset_model`
- `stage_presets`
- `stage1_duration_sec`, `stage2_duration_sec`, total `duration_sec`
- PIM structural counts: sources, processing elements, sinks
- NiFi structural counts: processors, connections
- `nifi_import` result when `--nifi` is used
- aggregate `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost_usd`
- `llm_calls`: per-call LLM log rows from SQLite for the run session
- `llm_usage_by_purpose`: per-purpose token/cost/duration totals

Use `llm_calls` for stage-level analysis. The aggregate token fields are only the run total.

## Recommended Experiment Matrix

For each test case, run at least:

```text
mode 0: direct NL -> JSON
mode 1: NL -> PIM -> adapter JSON
mode 3: NL -> PIM -> adapter JSON -> LLM correction
```

For provider comparisons, keep the test case and mode constant, then vary:

- PIM provider
- corrector provider
- timeout settings

Suggested case names:

- `currency-http-to-file`
- `kafka-to-postgres`
- `postgres-to-kafka`
- `s3-to-hdfs`

## Verification Commands

Fast local checks:

```powershell
.\.venv\Scripts\python.exe -m compileall src scripts
.\.venv\Scripts\python.exe -m pytest tests\unit\test_adapter_unit.py -v
```

Run adapter only:

```powershell
.\.venv\Scripts\python.exe scripts\run_adapter.py tests\fixtures\kafka_to_postgres.json
```

Run with a saved raw LLM response:

```powershell
.\.venv\Scripts\python.exe scripts\run_llm_fixture.py --llm-response saved_llm_output.json --out result.json
```

## Current Known Good Run

OpenRouter Qwen as PIM provider with Gemini/OpenRouter corrector reached NiFi successfully:

```text
preset: openrouter qwen/qwen3.6-plus
mode: 3
NiFi import: OK
processors: 2
connections: 1
tokens: 3190 input / 4208 output / 7398 total
estimated cost: 0.006507 USD
duration: 71.08s
```
