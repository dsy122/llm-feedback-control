[← How it works](02-how-it-works.md) · [Manual home](../index.md) · [Results →](04-results.md)

# API reference

Everything below is importable directly from the top-level package:

```python
from llm_feedback_control import run_audit, extract_iterative, ...
```

---

## Headline entry points

### `run_audit(text, verbose=True, generate=None) -> dict`

The full negative-feedback pipeline: regime gate → extraction → exact analysis →
grounded report, with explicit refusals. Works with no model (deterministic
fallback). Pass `generate` (a callable `f(prompt, fmt=None) -> str`) to choose a
backend.

Returns a dict with keys:

| key | present when | value |
|---|---|---|
| `text` | always | the input |
| `gate` | always | `{"verdict", "reason", "source"}`; verdict ∈ `finite_structural` / `model_only` / `mixed` |
| `result` | always | `"OK"`, `"OK (mixed: …)"`, or `"REFUSED: <reason>"` |
| `extraction` | not refused at gate | `{"via": "llm"\|"fallback", "states": [...], "transitions": [...]}` |
| `trace` | extraction non-empty | output of `exact_analysis` |
| `report_facts` | extraction non-empty | the deterministic checked summary (string) |
| `report_english` | extraction non-empty | optional LLM rewrite of the facts |

### `extract_iterative(text, max_iters=4, verbose=True, generate=None) -> (graph, initial, history, converged)`

The bounded positive-feedback loop (regenerative re-extraction to a fixed point).

- `graph` — the final state machine `{"states": [...], "transitions": [...]}`
- `initial` — the open-loop (iteration-0) snapshot, for before/after comparison
- `history` — list of `(iter, n_states, n_transitions, missing_states, missing_transitions)`
- `converged` — `True` if it reached a clean fixed point; `False` means the refusal
  clamp fired (iteration cap hit with residual gaps → treat as incomplete)

### `extract_form(text, schema, generate=None, max_iters=4, verbose=False) -> dict`

Extract form fields from free text, verified against a schema **and** the source.
Returns a dict: `record` (`{field: value}`), `result` (`"OK"` or `"REFUSED: could
not fill/validate required fields: …"`), `converged`, `iterations`, `gaps`
(remaining `{field, problem, hint}` items), and `initial` (open-loop first pass).

Schema: `{"fields": [{"name", "type", "required", …}]}`. Types: `string`, `email`,
`phone`, `number`, `currency`, `date`, `enum` (+ `values`), `pattern` (+ `pattern`
regex). With no model the regex detectors fill the detectable fields; same `record`
shape.

### `feedback_loop(text, *, extract, reference, repair, signature, finalize=None, max_iters=4, verbose=False, label="item") -> (candidate, initial, history, converged)`

The shared engine both targets run on — the injectable seam. Supply four callables:
`extract(text) -> candidate`, `reference(text, cand) -> [gaps]` (empty list ==
converged), `repair(text, cand, gaps) -> candidate | None`, `signature(cand) ->
hashable` (stall detection). Optional `finalize(text, cand) -> cand` is a
deterministic last-resort pass before the final check. The loop owns the bounded
positive feedback, the fixed-point test, and the refusal clamp.

---

## The negative-feedback pipeline parts

### `regime_gate(text, use_llm=True, generate=None) -> dict`
Classify text as `finite_structural`, `model_only`, or `mixed`. Clear cases use a
keyword heuristic; ambiguous cases consult the LLM (skipped if `use_llm=False` or no
model). Returns `{"verdict", "reason", "source"}` (`source` ∈ `heuristic` / `llm`).

### `gate_heuristic(text) -> (fin, cont)`
The raw cue counts behind the gate: number of finite-structural cues vs
continuous/belief cues. No network.

### `extract_workflow(text, generate=None) -> (graph, how)`
One-shot extraction: schema-validated LLM call with a deterministic regex fallback.
`how` is `"llm"` or `"fallback"`.

### `fallback_extract(text) -> graph`
The deterministic regex extractor (no model). States are ordered by first
appearance in the text so the first state is treated as the start.

### `exact_analysis(states, trans) -> dict`
Returns `{"primes": [...], "facts": {...}}`. `facts` is `graph_facts(...)`; `primes`
is the per-prime finite-field fingerprint (each entry: `prime`, `transient`,
`period`, `mode`, `bad_prime`, `readout_injective`). `trans` is an iterable of
`(from, to)` pairs.

### `graph_facts(states, trans) -> dict`
`{"terminal_states", "unreachable_states", "has_cycle"}` — pure graph analysis.

### `grounded_report(states, trace, llm=True, generate=None) -> (facts_str, english_str)`
Render the verified facts as text; optionally add an LLM rewrite that may name only
listed states. `trace` is the output of `exact_analysis`.

### `transfer_operator(states, trans, p) -> (M, idx)` and `fp_orbit(M, x0, p, max_steps=20000)`
Low-level pieces of the optional spectral fingerprint (mod-`p` transition matrix and
its orbit/cycle). Most users never call these directly.

### `valid(obj) -> bool`
Schema check: `obj` is a dict with list `states` and list `transitions`, each
transition a 2-element list.

### `norm(s) -> str`
Normalise a state name (lowercase, strip non-alphanumerics) for comparison.

---

## The positive-feedback parts

### `consistency_gaps(text, graph) -> (missing_states, missing_transitions)`
The deterministic reference: what does the text mention that the graph lacks? This
is what drives (and bounds) the re-extraction loop.

### `candidate_states(text) -> set` and `candidate_trans(text) -> set`
The regex candidate extractors used by `consistency_gaps`.

---

## The LLM client

### `gen(prompt, fmt=None, model=None, timeout=600) -> str`
Generate from the local Ollama small model. `fmt="json"` forces valid JSON. Greedy
decode (temperature 0). Raises `BackendError` (with guidance) if no server is
reachable.

### `gen_ceiling(prompt, fmt="json", timeout=600) -> str`
Generate from the "ceiling" model — a larger local Ollama model or OpenAI, per
`CEILING_BACKEND`. Used by the experiments to measure a small model against a larger
one.

### `info() -> str`
One-line summary of the current backend configuration.

### `doctor() -> dict`
Probe the configured backend and report availability. **Never raises** — safe to
call before anything is set up. Keys include `ollama_reachable`, `models_available`,
`small_model_present`. Backs `lfc --check`.

### `BackendError`
Raised by `gen` / `gen_ceiling` when no backend is reachable; the message explains
how to fix it. The high-level pipeline catches it internally and falls back to the
deterministic path.

### `__version__`
The package version string.

---

## The form target (helpers)

Exported at the top level:

### `form_field_gaps(text, schema, record) -> list`
The form reference: a list of `{field, problem, hint}` the record fails against the
schema and the source text (empty == complete). Drives the `extract_form` loop.

### `fallback_extract_form(text, schema) -> dict`
No-model baseline: regex detectors fill the detectable fields (email, phone,
currency, date, custom pattern); other fields are `None`.

More internals (`detect`, `validate`, `_snap_detectable`) live in
`llm_feedback_control.forms` for power users building a custom form reference.

---

## Controllers and circuits

Compositions of the loop primitives. See **[Controllers and circuits](07-controllers-and-circuits.md)**
for the narrative and examples. All exported at the top level.

### `llm_critic_reference(generate=None, *, rubric=None, model=None, max_gaps=8, verbose=False) -> reference`
Build a feedback `reference` whose controller is a low-power LLM: it asks the model
for specific, checkable problems with the candidate and returns them as a list of
strings (empty == satisfied). An *estimate*, not a guarantee. If no model is
reachable (or the reply won't parse) it returns no gaps — pair it with a
deterministic reference if a missing model must not silently pass. `rubric` focuses
the critique; `model` overrides the model name.

### `llm_critic_repair(generate=None, *, model=None) -> repair`
Build a `repair` that asks the model to revise the candidate to fix the critic's
gaps, returning a corrected object of the same JSON shape — or `None` (which stops
the loop, and fires the refusal clamp if gaps remain).

### `combine_references(*references, dedup=True) -> reference`
Summing junction: report the union of every sub-reference's gaps, so the loop
converges only when **all** are satisfied. Put the deterministic (exact) reference
first and a critic second to keep the guarantee as the floor. `dedup` drops repeated
gaps (by string form), order preserved.

### `quorum_reference(*references, quorum=None, similar=None, verbose=False) -> reference`
Instrumentation amp: keep only the gaps that **at least `quorum`** references
independently raise; reject single-reference gaps as noise (common-mode rejection).
Built for *independent* critics (different models). `quorum` defaults to a majority,
clamped to `[1, n]`; `combine_references` is the `quorum=1` extreme. `similar(a, b)
-> bool` decides when two free-text gaps are the same issue (default: word-overlap;
inject a stronger matcher for production).

### `cascade(*stages, stop_on_refusal=True) -> run`
Multi-stage amplifier. `run(x) -> (final, ok, trace)`: thread `x` through each stage,
feeding one stage's output to the next. A "stage" is any callable
`stage(input) -> (output, converged)`. `ok` is `True` iff every stage that ran
converged; with `stop_on_refusal=True` a refusing stage halts the chain. `trace` has
one `{"stage", "output", "converged"}` record per stage run.

### `loop_stage(*, extract, reference, repair, signature, finalize=None, max_iters=4, label="stage") -> stage`
Wrap a `feedback_loop` as a `cascade` stage: returns `stage(input) -> (output,
converged)` running the loop with `input` as its source.

### `schmitt_gate(low, high, *, start=False) -> classify`
Comparator with hysteresis. Returns a stateful `classify(score) -> bool`: flips to
`True` at/above `high`, back to `False` at/below `low`, and **holds** its last
verdict between them (the dead-band) — so a borderline score does not chatter.
Raises `ValueError` if `low > high`.

---

[← How it works](02-how-it-works.md) · [Manual home](../index.md) · [Results →](04-results.md)
