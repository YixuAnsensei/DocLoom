# DocLoom — Long-Document Automation Workbench for Local LLMs

> Produce tens of thousands of words of structured long-form documents — lab reports,
> paper-reading notes, Marp/Slidev slide decks — on a machine that can only run a
> ~30B-class local model.

DocLoom splits a long document into **independent, stateless per-chapter requests**
to any OpenAI-compatible local LLM API (llama.cpp-server, Ollama, vLLM…). Each
chapter carries only its own reference material, is written to disk as soon as it
finishes, and interrupted runs resume where they left off — sidestepping small
context windows and lossy context compression by design.

**Engine and tasks are fully separated**: there is exactly one copy of engine code;
a task is just a directory (`settings.json` + `prompts.json` + reference data).
Switching tasks = switching directories; a new task *type* = a new template.

[中文说明 / Chinese README](README.md)

## Features

- **Chapter-by-chapter generation with an optional State Chain** — inject the last
  N finished chapters into the current request for coherence
- **Exact token budgeting** via llama.cpp `POST /tokenize`, with automatic fallback
  to a heuristic estimate when unavailable
- **Four truncation strategies** (head / tail / middle / smart) with iterative
  shrink-and-verify against the real token counter
- **Two image paths**: send images directly to vision models (base64 multimodal),
  or pre-generate text captions (`docloom caption`) for text-only models
- **Candidate-draft revision flow**: `modify` produces a candidate draft (with a
  diff preview) instead of overwriting; `accept` / `reject` decides its fate.
  In-place mode and resumable batch modification are also available
- **Pre-flight review**: `docloom review` writes a full preview (per-chapter
  prompts, references, token budgets, missing-file checks) before you spend GPU time
- **Web UI**: `docloom serve` — edit prompts, run generation, watch logs, and
  handle candidate drafts from the browser
- **Atomic writes everywhere** — configs and reports can't be corrupted mid-write

## Quick start

```bash
pip install -r requirements.txt
cd DocLoom

python -m docloom templates                       # list templates
python -m docloom new my_report --template report # create a task
# drop PDFs/DOCX into workspace/my_report/data/raw/, then:
python -m docloom parse
python -m docloom extract-images                  # optional
python -m docloom caption                         # optional, for text-only models
# edit workspace/my_report/config/prompts.json
python -m docloom review                          # pre-flight check
python -m docloom run                             # generate (Ctrl+C safe, resumable)

python -m docloom modify 3 -p "tighten paragraph 2"
python -m docloom accept 3                        # or reject 3

python -m docloom serve                           # Web UI at http://127.0.0.1:8600
```

## Layout

```
docloom/      engine (single copy of code)
templates/    task templates: settings.json + prompts.json + description.md
workspace/    your tasks: config/ + data/{raw,processed,extracted_images} + output/
```

Create your own template by copying a tuned task's `config/settings.json` and
`config/prompts.json` into `templates/<name>/` — that is the entire cost of
porting DocLoom to a new document type.

See the [Chinese README](README.md) for the full settings reference and command table.

## License

MIT
