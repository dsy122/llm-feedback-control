# llm-feedback-control — user manual

Reliable, checkable structured data out of a small, local language model, by
wrapping it in a deterministic feedback loop: **verify against a reference → fill
the gaps → refuse when it can't be verified.**

It's one engine pointed at different **targets**. Two ship today — workflow /
state-machine extraction (`run_audit`) and form-field extraction (`extract_form`) —
and the loop is public and injectable, so you can add your own.

New here? Read **Getting started**, then **How it works**. Looking something up? Go
straight to the **API reference** or the **FAQ**.

## Contents

1. [Getting started](manual/01-getting-started.md) — install, the API, the `lfc`
   CLI, choosing/​bringing a model, configuration.
2. [How it works](manual/02-how-it-works.md) — the operational-amplifier model:
   negative vs positive feedback, refusal-as-stabilizer, and why the engine is
   general (any target = a schema + a deterministic reference).
3. [API reference](manual/03-api-reference.md) — every public function.
4. [Results](manual/04-results.md) — the measured numbers, method, and honest scope.
5. [Worked examples](manual/06-examples.md) — actual run transcripts (a small model
   reaching a ~28 GB one; form extraction recovering a hallucinated value and
   refusing a missing field).
6. [FAQ](manual/05-faq.md) — "do I need a GPU?", "what models?", "does it work
   offline?", "why did it refuse?" …

[Changelog](CHANGELOG.md) · [Project README](../README.md) ·
[Repository](https://github.com/pcoz/llm-feedback-control)

## The two ideas worth remembering

1. **The model is the amplifier; deterministic code is the feedback network.** You
   trade a little of the model's raw "gain" (fluency) for precision, stability, and
   auditability — exactly the trade an op-amp makes.
2. **Refusal is a feature.** A system that says "this input isn't something I can
   verify" is more useful than one that always answers. Refusal is what keeps the
   loop honest. ([How it works §5](manual/02-how-it-works.md))
