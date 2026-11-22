# Evaluation

`tests/evals/cases.py` defines 20 cases (6 normal, 6 blocked/inaccessible, 4 security, 4 reliability).
`python -m tests.evals.run` writes `docs/eval_results.md`.

- **Mock mode** (`USE_MOCK=1`) verifies pipeline behaviour: outcomes, branching, citation resolution. It says nothing about model quality.
- **Live mode** must be run on Ollama for at least two models. Record per model: latency, JSON-repair rate, and a manual
  label for >=10 claims (supported/contradicted correct?), citation accuracy (does the linked source back the claim?),
  and originality. Put the scorecard and failure analysis in `docs/eval_results.md`.
