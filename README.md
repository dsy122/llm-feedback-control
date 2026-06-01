# llm-feedback-control

**Wrap a small, local LLM in a deterministic feedback network so it knows what
it can compute exactly, does so, and refuses the rest.**

The governing analogy is an operational amplifier. A raw LLM is a high-gain,
open-loop device: enormous fluency, but open-loop it drifts and hallucinates.
Close the loop with a deterministic reference and you trade some raw gain for
**precision, stability, and auditability** — a precision instrument instead of
a railing amplifier.

- **Negative feedback** — a *regime gate* (route the exactly-computable part to
  a deterministic engine, keep the genuinely-fuzzy part in the LLM), exact
  analysis, schema validation, and explicit **refusal** (out-of-regime input,
  non-injective readouts) → stabilises and grounds the output.
- **Positive feedback** — a bounded *regenerative loop*: re-extract to a
  text↔graph **fixed point**, recovering completeness the one-shot pass missed.
  Positive feedback is where capability *and* instability both live, so it is
  bounded by a deterministic consistency reference + a **refusal clamp** on
  non-convergence. **Refusal-as-stabilizer** is the principle that makes the
  regenerative loop safe.

**Why it matters:** this lets you get **higher-quality, auditable structured
output from a *small* model** — trading a few extra passes (latency) for
accuracy, with no extra parameters, no special mathematics, and no cloud. It
runs entirely on a laptop with a local Ollama model.

## What's measured so far (indicative; small corpora, a 3.8B local model)

| question | result |
|---|---|
| Can a small model extract a finite transition system? | states P/R ≈ **1.00 / 0.92**, transitions **0.93 / 0.96** (valid JSON every call) |
| Does the regime gate refuse continuous/belief input? | **1.00** precision/recall on a clean corpus (brittle on ambiguous "mixed" cases — open) |
| Do grounded reports hallucinate less than plain? | directional: fewer unsupported entities |
| Does the feedback loop raise small-model quality? | states F1 **0.96 → 1.00**, recovers dropped branches; converges to a fixed point |

These are honest first results, not benchmarks. The gate's "mixed" detection and
the magnitude of the small-vs-big uplift on *harder* inputs are open (see
`hard_corpus.py`).

## Files

| file | what it is |
|---|---|
| `llm.py` | shared client: a local Ollama small model (`gen`) + an optional stronger "ceiling" model (`gen_ceiling`, local or OpenAI). All env-configurable. |
| `auditor.py` | the negative-feedback pipeline: extract → gate → exact analysis → readout/refuse → grounded report. Demos M1 (audit), M2 (gate refusal), M3 (non-injective-readout refusal) + a gate-hardening test. |
| `feedback.py` | the bounded **positive-feedback** loop: regenerative re-extraction to a fixed point, clamped by a deterministic consistency reference + refusal. |
| `prototype_test.py` | the three open-question tests (extraction / gate / grounding). |
| `quality_uplift.py` | open-loop vs closed-loop F1 on the small model. |
| `hard_corpus.py` | small open vs closed vs a bigger ceiling model on messy inputs; reports % of the small→big gap the loop recovers. |

The "exact analysis" is standard graph analysis (reachability, cycles,
terminals); a finite-field spectral fingerprint is included as an *optional*
extra (and powers the M3 non-injective-readout refusal demo). It is honestly
redundant with graph analysis for most workflow audits — keep it or drop it.

## Run it (local — no GPU, no cloud)

```bash
pip install -r requirements.txt          # networkx, numpy (stdlib does the rest)
# install Ollama (https://ollama.com) and pull a small model:
ollama pull phi3:mini

python auditor.py            # M1/M2/M3 + gate hardening
python quality_uplift.py     # open-loop vs closed-loop
python feedback.py           # the positive-feedback loop recovering a dropped branch
python hard_corpus.py        # small vs ceiling on hard inputs
```

Configuration (env vars; see `llm.py`):

```
OLLAMA_HOST      default http://localhost:11434
LFC_MODEL        the small model under test           (default phi3:mini)
LFC_CEILING      a bigger local Ollama ceiling model  (default llama3.1:8b)
CEILING_BACKEND  "ollama" (default) or "openai"
OPENAI_API_KEY   required iff CEILING_BACKEND=openai   (OPENAI_MODEL default gpt-4o-mini)
```

A small model runs comfortably on CPU — **no EC2/GPU is needed for this work.**
The only thing that benefits from a bigger box is hosting a large *ceiling*
model fast; the ceiling is optional, and an API call serves the same purpose.

## Honest scope

- **A reliability architecture, not a model improvement.** The win is "the
  system knows what it can compute exactly and refuses the rest" — orthogonal
  to model scale. It helps on the *structured / verifiable slice* (workflows,
  state machines, configs), not open-ended generation.
- **It uses no special mathematics.** The deterministic reference is plain
  graph/text consistency. (The optional finite-field fingerprint is just an
  extra exact check, not the source of value.)
- **Needs a deterministic reference.** Where there's nothing to check against,
  the gate (correctly) refuses to claim exactness.

## Origin

This project is the practical, validated spin-off of an internal research
investigation. The investigation's grander mathematical claims did not hold up
under measurement; this engineering architecture — LLM feedback control with
refusal-as-stabilizer — is the part that did. It stands on its own.
