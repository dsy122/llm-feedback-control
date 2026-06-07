[← FAQ](06-faq.md) · [Manual home](../index.md)

# Controllers and circuits

Earlier chapters showed the loop with a *deterministic* controller: the
`reference` is plain code — graph consistency, a field schema — and whatever it
checks, it checks with a guarantee. This chapter is about the other things you
can put in the controller seat, and how to wire several feedback blocks together.
It keeps leaning on the op-amp analogy the rest of the library uses, because the
analogy keeps paying off: the loop does not care *what* sits in the feedback
path, only whether that element is exact or estimated.

Everything here is additive and optional. The deterministic pipeline from the
earlier chapters is unchanged, and all of it still runs with no model at all.

## The controller seat

Recall the loop's shape (see [How it works](02-how-it-works.md)). One callable is
the controller:

```
reference(text, candidate) -> list of gaps        # [] means "satisfied"
```

`run_audit` uses `consistency_gaps`; `extract_form` uses a field schema. Both are
exact. The loop is indifferent to how `reference` is implemented, so you can put
other things there — including a model.

## A low-power model as the critic

A deterministic reference can only check what you can write code for. Plenty of
real problems have a fuzzy quality dimension no rule captures: is the answer
*relevant*, is it *coherent*, did it actually answer the question? For those you
can put a small language model in the controller seat — a **critic**.

```python
from llm_feedback_control import feedback_loop
from llm_feedback_control.critic import llm_critic_reference, llm_critic_repair

reference = llm_critic_reference(generate=my_small_model)   # the controller
repair    = llm_critic_repair(generate=my_small_model)      # how to fix gaps

cand, initial, history, converged = feedback_loop(
    text, extract=my_extract, reference=reference, repair=repair,
    signature=lambda c: tuple(sorted(c.items())))
```

The critic is asked for *specific, checkable problems* with the candidate; an
empty list is its "satisfied", which is the loop's fixed point. If no model is
reachable it raises **no** gaps (it cannot critique, so it does not block) — keep
a deterministic reference alongside it if a missing model must not silently pass.

**This is an estimate, not a guarantee.** A model critic can pass a bad answer
and fail a good one. The loop still terminates only because of `max_iters` and
the refusal clamp, not because the critic is sound. So the rule for the whole
chapter is: **keep at least one exact element in the loop.** Anything that *must*
be right belongs in a deterministic reference; the critic is for breadth on top.

## Summing junction — `combine_references`

To keep the exact floor and add the critic's breadth, sum the two controllers.
The combined reference reports the union of their gaps, so the loop converges
only when **both** are satisfied.

```python
from llm_feedback_control import combine_references

reference = combine_references(exact_reference, llm_critic_reference(my_small_model))
```

This is a summing junction: the exact reference guarantees the hard constraints
and the refusal; the critic adds the fuzzy checks. Put the exact one first.

## Instrumentation amp — `quorum_reference`

A single model critic has a failure mode worth naming: if it shares the
generator's blind spots — above all, if it is the *same model* — it rubber-stamps
the generator's mistakes. A model checking itself is a crowd of one.

The fix is independence, and a circuit for it. Run two or more **independent**
critics (different models) and keep only the gaps a *quorum* of them
independently raise; reject what any single critic raises on its own as noise.

```python
from llm_feedback_control import quorum_reference

reference = quorum_reference(
    llm_critic_reference(model_a),
    llm_critic_reference(model_b),
    quorum=2)            # both must agree before a gap drives a repair
```

That rejection of per-critic idiosyncrasy is the **common-mode rejection** of an
instrumentation amplifier; independence is what makes it real. `combine_references`
is the `quorum=1` extreme (any critic's gap counts); unanimous is `quorum = number
of critics`. The trade-off is explicit and yours: a higher quorum rejects more
noise but can miss a real issue only one critic caught. Gap-matching across
critics ("is this the same complaint, differently worded?") is itself fuzzy; a
crude word-overlap matcher is the default, and you can inject a stronger one via
`similar=`.

## Multi-stage amplifier — `cascade`

When a job has stages — extract, then normalise, then enrich — pipe one
controlled loop's output into the next. Each stage is exact-checked, so error
cannot compound silently down the chain, and a stage that refuses stops the
cascade rather than feeding an untrusted result onward.

```python
from llm_feedback_control import cascade, loop_stage

stage1 = loop_stage(extract=..., reference=..., repair=..., signature=...)
stage2 = loop_stage(extract=..., reference=..., repair=..., signature=...)

final, ok, trace = cascade(stage1, stage2)(source_text)
# ok is False if any stage refused; trace has one record per stage that ran.
```

A "stage" is any callable `stage(input) -> (output, converged)`; `loop_stage`
just wraps a `feedback_loop` as one, so you can also drop in plain functions.

## Comparator with hysteresis — `schmitt_gate`

A routing decision driven by a single threshold *chatters*: a confidence score
hovering at the line flips accept/refuse on every wobble. A Schmitt trigger fixes
that with two thresholds and a dead-band between them — the verdict is sticky.

```python
from llm_feedback_control import schmitt_gate

gate = schmitt_gate(low=0.4, high=0.6)   # flips on >=0.6, back on <=0.4, else holds
route_here = gate(score)                 # stable across borderline scores
```

It flips to `True` only above `high`, back to `False` only below `low`, and holds
its last verdict in between — so a noisy score near the boundary stops oscillating.

## See it run (no model needed)

Both new modules ship offline, scripted demos — they use a fake `generate`, so
they run on a bare `pip install` with no Ollama and no network:

```bash
python -m llm_feedback_control.critic      # critic loop + the instrumentation amp
python -m llm_feedback_control.circuits    # the cascade + the Schmitt trigger
```

## The one rule to carry away

Every circuit here is worth something only because it keeps an exact element in
the loop. A pure model-only circuit — a critic critiquing a critic with no
deterministic reference and no refusal — is an amplifier with no stable reference
to feed back to: huge gain, and it drifts. The critic and the circuits widen what
the loop can react to; the deterministic reference and the refusal clamp are what
the guarantees still rest on.

[← FAQ](06-faq.md) · [Manual home](../index.md)
