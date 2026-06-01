# Results

**Read this as direction, not as a benchmark.** Every number below comes from a
small, hand-built corpus and a single small model with greedy decoding. The point
is to show the *shape* of the effect — that closing the loop measurably improves a
small model's structured output — not to claim a leaderboard position.

All experiments are reproducible from the scripts in [`../experiments/`](../experiments),
which are configured entirely by environment variable (see [usage.md](usage.md)).

## 1. Headline: a small model reaching a big one

**Question.** On *hard* inputs (messy prose, passive voice, synonyms,
co-reference, distractor sentences), how much of the quality gap between a small
model and a much larger one does the feedback loop close?

**Setup.** Three configurations on a 5-item branchy workflow corpus
(`experiments/hard_corpus.py`):

- **small-open** — `phi3:mini` (3.8B), one-shot extraction;
- **small-closed** — the same model + the bounded positive-feedback loop;
- **ceiling** — `mixtral:8x7b-instruct-v0.1-q4_K_M` (~28 GB, ~7× the size),
  one-shot, run on an EC2 large-RAM instance.

Metric: states & transitions F1 against ground truth.

| configuration | states F1 | transitions F1 |
|---|---|---|
| small-open (phi3:mini, one-shot) | 0.98 | 0.89 |
| **small-closed (phi3:mini + loop)** | **1.00** | **0.90** |
| ceiling (mixtral ~28 GB, one-shot) | 1.00 | 0.91 |

**Gap to the ceiling recovered by the loop: 100% on states, 77% on transitions.**

The closed-loop small model **matches the ~28 GB model**, and on several individual
workflows it *beat* the big model on transitions (e.g. 1.00 vs 0.88, 0.91 vs 0.73)
— because the deterministic consistency reference catches edges that raw fluency at
scale either invents or drops. The cost is a few extra passes (latency), not extra
parameters.

## 2. The uplift in isolation

**Question.** Holding the model fixed, does closing the loop raise extraction
quality? (`experiments/quality_uplift.py`)

On a ground-truthed corpus, the same `phi3:mini` open-loop vs closed-loop:

- states F1: **0.96 → 1.00**
- transitions F1: improved, converging to a clean fixed point on most items

The gain comes entirely from the deterministic reference re-asking about dropped
branches — **no special mathematics**, just regex text↔graph consistency.

## 3. The three prototype questions

`experiments/prototype_test.py` tests the assumptions the architecture rests on.

**Q1 — Can a small model extract a finite transition system reliably?**
With schema validation + deterministic fallback, on the clean corpus:
states precision/recall ≈ **1.00 / 0.92**, transitions ≈ **0.93 / 0.96**, valid
JSON on every call. Good enough to build on.

**Q2 — Does the regime gate refuse the right things?**
On a clean finite-vs-continuous corpus, **1.00 precision/recall** — continuous and
belief-driven inputs are correctly refused. *Caveat:* the gate is **brittle on
deliberately mixed inputs** (text that is genuinely part-finite, part-continuous).
Hardening the "mixed" verdict is the main open problem; the LLM tie-break helps but
isn't reliable yet.

**Q3 — Are grounded reports more auditable than plain ones?**
Directional: reports written from verified facts mention fewer unsupported entities
than free-form explanations. The verifier here is a crude entity-support proxy, so
treat this as a positive signal, not a measurement.

## 4. Honest scope and limitations

- **Small corpora.** Tens of items, not thousands. The numbers are indicative.
- **One small model.** Mostly `phi3:mini`. The *mechanism* should generalise (it's
  model-agnostic), but that hasn't been swept across model families.
- **The "mixed" regime is the weak point.** Clean finite-vs-continuous separation
  is solid; genuinely mixed inputs are not yet reliably classified.
- **The spectral fingerprint is optional and largely redundant** with plain graph
  analysis for workflow audits. It exists mainly to demonstrate the non-injective
  readout refusal (demo M3).
- **It only helps where a deterministic reference exists.** For open-ended
  generation with nothing to check against, the gate refuses — by design.

## 5. Reproducing

```bash
pip install -e ".[dev]"
ollama pull phi3:mini

python experiments/prototype_test.py     # Q1 / Q2 / Q3
python experiments/quality_uplift.py      # open-loop vs closed-loop
python experiments/hard_corpus.py         # small vs ceiling (set LFC_CEILING)
```

To reproduce the headline against a large ceiling model without a big local GPU,
the `aws/` tooling provisions an EC2 instance, caches the model on S3, and runs
`hard_corpus.py` there; see the scripts in [`../aws/`](../aws).
