# Campaign Runner

`scripts/run_campaign.py` is the orchestration layer for large thesis experiments.
It does not replace `scripts/run_nl_test.py`; it manages many `run_nl_test.py`
executions and keeps their artifacts in a reproducible structure.

## Goals

- keep all runs in one indexed place;
- avoid mixing different experiments;
- execute cases sequentially so NiFi validations do not interfere with each other;
- support pause/resume when the operator or agent needs to intervene;
- preserve researcher comments for later analysis in the thesis.

## Directory Layout

```text
test_runs/
  campaigns/
    <campaign-id>/
      campaign.json
      summary.csv
      manifest.snapshot.yaml
      notes.jsonl
      runs/
        <run-id>/
          query.txt
          run_request.json
          raw_report.json
          run_summary.json
          pim.yaml
          nifi.json
          runner_stdout.log
          runner_stderr.log
          notes.jsonl
```

`campaign.json` is the main registry.
`summary.csv` is the thesis-friendly flat export.
Each run directory contains both raw and normalized outputs.

## Basic Workflow

1. Create a manifest from the template:

```powershell
.\.venv\Scripts\python.exe scripts\run_campaign.py template `
  --out config\campaigns\my_campaign.yaml
```

2. Edit the manifest: presets, modes, cases, query texts, manual flags.

3. Initialize the campaign:

```powershell
.\.venv\Scripts\python.exe scripts\run_campaign.py init `
  --manifest config\campaigns\my_campaign.yaml
```

4. Run queued experiments:

```powershell
.\.venv\Scripts\python.exe scripts\run_campaign.py run `
  --campaign thesis-global-validation-202605
```

If you forgot a mode, preset, or case and already have partial results, sync the
existing campaign with an updated manifest instead of recreating it:

```powershell
.\.venv\Scripts\python.exe scripts\run_campaign.py sync `
  --campaign thesis-global-validation-202605 `
  --manifest config\campaigns\my_campaign.yaml
```

5. Check summary:

```powershell
.\.venv\Scripts\python.exe scripts\run_campaign.py status `
  --campaign thesis-global-validation-202605 --verbose
```

If a run is ready for manual NiFi inspection, import it onto the live canvas and keep it there:

```powershell
.\.venv\Scripts\python.exe scripts\run_campaign.py materialize `
  --campaign thesis-global-validation-202605 `
  --run-id <run-id>
```

The command returns:
- `pg_id` of the created process group;
- validation state at import time;
- the exact `manual_test_checklist` for the run.

After you finish checking the flow, clean it up:

```powershell
.\.venv\Scripts\python.exe scripts\run_campaign.py cleanup-nifi `
  --campaign thesis-global-validation-202605 `
  --run-id <run-id>
```

6. Add notes and manual decisions:

```powershell
.\.venv\Scripts\python.exe scripts\run_campaign.py note `
  --campaign thesis-global-validation-202605 `
  --run-id <run-id> `
  --author Dmitry `
  --kind operator_comment `
  --text "После ручной проверки flow импортировался, но требует настройки пути."
```

7. Move the run forward after manual work:

```powershell
.\.venv\Scripts\python.exe scripts\run_campaign.py set-status `
  --campaign thesis-global-validation-202605 `
  --run-id <run-id> `
  --status completed `
  --author Dmitry `
  --note "Ручная проверка в NiFi пройдена."
```

## Manifest Semantics

Main sections:
- `campaign`: id, title, owner, thesis metadata.
- `defaults`: baseline settings for all cases.
- `cases`: concrete NL scenarios.

Supported defaults and case overrides:
- `presets`: base preset ids for `run_nl_test.py`.
- `modes`: any subset of `0`, `1`, `2`, `3`.
- `stage_presets`: `pim`, `psm`, `corrector`.
- `repeat`: number of repeated attempts per configuration.
- `timeout_sec`: per-stage timeout for `run_nl_test.py`.
- `nifi_validate`: whether to call `--nifi`.
- `manual_nifi_required`: whether successful automatic runs should pause for human functional testing.
- `requires_user_input`: whether successful runs should pause for discussion before continuing.
- `stop_after_statuses`: statuses that should stop the current batch execution.

Note: `run_nl_test.py` currently supports one shared corrector preset for both
error correction and NiFi correction stages. The campaign manifest reflects that
with a single `corrector` key.

## Status Model

- `queued`: waiting to be executed.
- `running`: currently executing.
- `needs_user_input`: pause for clarification, interpretation, or research decision.
- `needs_nifi_manual_test`: automatic validation finished; human functional testing is next.
- `completed`: run is finished and accepted.
- `failed_generation`: no valid pipeline result was produced.
- `failed_import`: NiFi import failed or validation errors remained.
- `cancelled`: excluded from the current campaign.

## How To Record Human Input

Use notes aggressively. Comments are research data.

Recommended `kind` values:
- `operator_comment`
- `manual_nifi_result`
- `research_note`
- `comparison_note`
- `status_change_note`

Good note examples:
- why a run was accepted despite minor issues;
- what had to be changed manually in NiFi;
- whether the generated YAML was understandable to the engineer;
- how long the manual baseline took for the same case;
- why a provider/mode combination was excluded from later batches.

The important rule is simple: if a judgment matters for the thesis, attach it to
the concrete `run_id`.

When asking the operator to test a run, always provide the concrete checklist
from `manual_test_checklist` instead of a generic "check it in NiFi" instruction.

## Practical NiFi Note

For manual file-output checks on the current stand, prefer output directories
without underscores in the path. In the observed NiFi runs, file writing behaved
more reliably on paths without `_` than on otherwise equivalent paths with `_`.
