# OmniAudit

OmniAudit is an offline-first Python 3.11 CLI for **agentic AST test generation,
sandboxed triage, and deterministic auto-patching**. It inspects Python source
without importing it, generates edge-case pytest tests, runs those tests in a
disposable workspace, classifies failures, synthesizes a unified diff, and
verifies the patched source without touching the original working tree.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m omniaudit scan examples/buggy_pkg --benchmark --output reports/latest_report.md
```

The CLI is standard-library-only at runtime. Pytest is the pinned development
and sandbox test dependency. No API key is required for the local deterministic
agent; `.env.example` documents the optional environment contract.

## Single-command test

```bash
make test
```

The equivalent direct command is:

```bash
python3 -m pytest -q
```

## Demo command

```bash
make demo
```

This writes `reports/latest_report.md`. The demonstration intentionally starts
with three bugs in `examples/buggy_pkg/math_ops.py`:

- `average([])` divides by zero instead of raising a clear `ValueError`.
- `tail(items, n)` returns the first `n` items instead of the last `n` items.
- `append_item` shares a mutable default list between calls.

## Architecture

```text
                         +----------------------+
                         | python -m omniaudit  |
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         | CLI + Markdown report|
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         | AST planner           |
                         | functions, args,      |
                         | defaults, complexity  |
                         +----------+-----------+
                                    |
                    +---------------+----------------+
                    | ThreadPoolExecutor            |
                    v                                v
             +--------------+                 +--------------+
             | local agent  |       ...       | local agent  |
             +------+-------+                 +------+-------+
                    |                               |
                    +---------------+---------------+
                                    v
                         +----------------------+
                         | tempfile sandbox     |
                         | pytest + 5s timeout  |
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         | triage -> diff ->    |
                         | patched verification |
                         +----------------------+
```

## Benchmark interpretation

The `--benchmark` flag measures the same module work once with one worker and
once with the configured worker pool. Wall-clock values depend on the host;
the report records the actual values and computes `serial / parallel`.

| Workload | Serial workers | Parallel workers | Expected result |
| --- | ---: | ---: | --- |
| One small module | 1 | 4 | Correctness is identical; process startup dominates |
| Several independent modules | 1 | 4 | Parallel execution reduces wall-clock time when CPU is available |
| Generated tests and patch verification | 1 | 4 | Both paths run the same offline pytest checks |

## Production-minded safeguards

- AST planning never imports target modules.
- Sandbox commands use an argument vector, `shell=False`, `stdin=DEVNULL`, a
  minimal environment, disabled third-party pytest autoloading, and a timeout.
- Patches are held in memory and tested in a temporary copy; the input source
  remains unchanged.
- Report paths are normalized to repository-relative names and captured
  subprocess output is sanitized before it is written.
- The default local agent makes no network calls and needs no credentials.

## Project layout

```text
omniaudit/
├── omniaudit/       # planner, sandbox, agents, CLI
├── examples/        # deterministic buggy package
├── tests/            # offline unit and integration coverage
├── reports/          # generated Markdown report
├── pyproject.toml
├── requirements.txt
├── requirements.lock
├── Dockerfile
└── Makefile
```

## License

MIT. See `LICENSE`.
