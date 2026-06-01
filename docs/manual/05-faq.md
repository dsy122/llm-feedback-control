# FAQ

### Does it work without a language model?

Yes. The deterministic pipeline — a regex extractor plus exact graph analysis —
runs on a bare `pip install` and returns a real, checked result. A model only
improves the *extraction* step. Try it:

```python
from llm_feedback_control import run_audit
print(run_audit("A ticket opens in New. New goes to Assigned. Assigned goes to Resolved.")["report_facts"])
```

### Do I need a GPU?

No. The recommended small model (`phi3:mini`, 3.8B) runs comfortably on a CPU. A
GPU or large-RAM box only helps if you want to host a *large* "ceiling" model fast —
and the ceiling is optional (it's used to measure a small model against a big one).

### What models can I use?

Anything. Out of the box it talks to a local **Ollama** model. Set
`CEILING_BACKEND=openai` to use the **OpenAI** API (no SDK — stdlib HTTP). Or pass
your own `generate=` callable (`f(prompt, fmt=None) -> str`) to use Anthropic, a
local server, or any endpoint. See [Getting started](01-getting-started.md).

### Why is the output sometimes "REFUSED"?

That's the system working as designed. It refuses when:

- the input isn't a finite step-by-step process (e.g. continuous/belief prose);
- nothing finite could be extracted;
- a result can't be made exact (a non-injective readout);
- the positive-feedback loop couldn't converge within its cap.

A refusal with a reason is more useful than a confident guess. See
[How it works](02-how-it-works.md) §5, "refusal-as-stabilizer".

### What does "feedback control" mean here? Is this control theory / electronics?

It's an **analogy**, explained in full in [How it works](02-how-it-works.md). In
short: a raw LLM behaves like a high-gain amplifier (fluent but drifts); wrapping it
in a deterministic "feedback loop" trades some fluency for precision and
auditability, exactly as negative feedback tames an op-amp. You don't need any
electronics background to use the library.

### What's the "spectral fingerprint" / the finite-field stuff?

An **optional** extra exact check (iterating the transition matrix under modular
arithmetic) that can flag when two different internal states would collapse to the
same summary, triggering a refusal. It's mathematically tidy but **largely redundant
with plain graph analysis** for workflow audits. You can ignore it; nothing else
depends on it.

### Is this "no special mathematics" claim real?

Yes. The deterministic reference that drives and bounds the loops is plain regex
text↔graph consistency and standard graph algorithms (reachability, cycle
detection). The optional fingerprint is the only "fancy" math, and it's not load-
bearing.

### How big can the input be?

The intended domain is human-scale processes — workflows, state machines, configs:
dozens of states, not millions. The exact analysis is cheap at that scale.

### Does it phone home / need the cloud?

No. With a local Ollama model it runs entirely offline. The optional `aws/` tooling
is only for the (optional) experiment of hosting a large ceiling model on EC2; the
library itself never needs it.

### Is it stable / production-ready?

It's an early (0.1.x), honestly-scoped release. The architecture and the
deterministic core are solid and tested; the measured results are *indicative* on
small corpora, and the "mixed"-regime classifier is the known weak spot (see
[Results](04-results.md)). Treat it as a reliable building block for the structured,
verifiable slice — not a turnkey general extractor.

### How do I reproduce the numbers in the README?

See [Results](04-results.md) §5. The scripts live in
[`../../experiments/`](../../experiments).
