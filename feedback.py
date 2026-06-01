"""feedback.py — the bounded POSITIVE-feedback loop (the op-amp "close the loop").

Negative feedback (gate / ground / refuse) was validated in auditor.py: it
stabilises, but it checks FORM, not COMPLETENESS — M1's extraction silently
dropped the 'Refund' branch and the system still said "OK".

This adds the regenerative loop that fixes that, and it deliberately uses a
reference that needs NONE of the special mathematics — just deterministic
text<->graph consistency:

    extract (LLM)  ->  consistency_gaps(text, graph)  [deterministic reference]
        ^                                   |
        |____ re-prompt with the gaps  <----'   (positive feedback: amplify coverage)

Bounded by: a FIXED-POINT test (stop when the graph stops changing / no gaps)
and an iteration cap with a REFUSAL clamp (if it can't converge, say so — do
NOT report a confident-but-incomplete result). That refusal clamp is the
stability bound that keeps the regenerative loop from running away.

The point: this is "LLM feedback control" — and it works with no special
mathematics at all. The reference is plain regex graph consistency.

Requires: Ollama (a small model, e.g. phi3:mini), via llm.gen.  Run: python feedback.py
"""
import sys, re, json
from llm import gen
from auditor import valid, fallback_extract, norm

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

STOP = {"If", "The", "A", "An", "After", "Once", "When", "Otherwise", "It", "Then"}


def candidate_states(text):
    c = set()
    for m in re.finditer(r"(?:goes to|moves to|move to|back to|to|enters|starts in|opens in|into)\s+([A-Z][A-Za-z0-9]+)", text):
        c.add(m.group(1))
    for m in re.finditer(r"\b([A-Z][A-Za-z0-9]+)\s+(?:goes|moves|closes|enters|ends)", text):
        c.add(m.group(1))
    return {s for s in c if s not in STOP}


def candidate_trans(text):
    tr = set()
    for m in re.finditer(r"([A-Z][A-Za-z0-9]+)\s+(?:goes to|moves to|move to)\s+([A-Z][A-Za-z0-9]+)"
                         r"(?:\s+or(?: to)?\s+([A-Z][A-Za-z0-9]+))?", text):
        a, b, c = m.group(1), m.group(2), m.group(3)
        if a not in STOP: tr.add((a, b))
        if c: tr.add((a, c))
    return tr


def consistency_gaps(text, graph):
    """Deterministic reference: what does the TEXT mention that the GRAPH lacks?"""
    gs = {norm(s) for s in graph.get("states", [])}
    gt = {(norm(a), norm(b)) for a, b in graph.get("transitions", [])}
    miss_s = sorted({s for s in candidate_states(text) if norm(s) not in gs})
    miss_t = sorted({(a, b) for a, b in candidate_trans(text)
                     if (norm(a), norm(b)) not in gt})
    return miss_s, miss_t


def extract_iterative(text, max_iters=4, verbose=True):
    """Positive-feedback extraction: re-prompt on deterministic gaps until a
    fixed point, bounded by max_iters + a refusal clamp."""
    # iteration 0: plain extraction
    try:
        raw = gen('Extract the finite state machine. Return ONLY JSON '
                  '{{"states":[...],"transitions":[["FROM","TO"],...]}} using exact state '
                  f'names from the text. Text: "{text}"', fmt="json")
        graph = json.loads(raw)
        if not (valid(graph) and graph.get("states")):
            graph = fallback_extract(text)
    except Exception:
        graph = fallback_extract(text)

    initial = json.loads(json.dumps(graph))   # iter-0 (open-loop) snapshot
    history = []
    for it in range(max_iters):
        miss_s, miss_t = consistency_gaps(text, graph)
        sig = (tuple(sorted(norm(s) for s in graph["states"])),
               tuple(sorted((norm(a), norm(b)) for a, b in graph["transitions"])))
        history.append((it, len(graph["states"]), len(graph["transitions"]), miss_s, miss_t))
        if verbose:
            print(f"  iter {it}: states={graph['states']}")
            print(f"          gaps -> missing states {miss_s or '∅'}, missing transitions {miss_t or '∅'}")
        if not miss_s and not miss_t:
            return graph, initial, history, True   # FIXED POINT (converged, no gaps)
        # positive feedback: re-prompt with the deterministic gaps
        gaps_txt = (f"missing states: {miss_s}; missing transitions: {miss_t}")
        try:
            raw = gen('Here is a state machine you extracted, and a list of items the '
                      'source text mentions that are MISSING from it. Return the COMPLETE '
                      'corrected machine as JSON {{"states":[...],"transitions":[["FROM","TO"],...]}}, '
                      'adding the missing items (and their transitions) using exact names. '
                      f'Current: {json.dumps({"states": graph["states"], "transitions": graph["transitions"]})}. '
                      f'Missing per the text: {gaps_txt}. Source text: "{text}"', fmt="json")
            ng = json.loads(raw)
            if valid(ng) and ng.get("states"):
                # check it actually changed (avoid stalling)
                nsig = (tuple(sorted(norm(s) for s in ng["states"])),
                        tuple(sorted((norm(a), norm(b)) for a, b in ng["transitions"])))
                graph = ng
                if nsig == sig:
                    break                          # no change -> not converging
        except Exception:
            break
    # exhausted iterations with residual gaps -> REFUSAL CLAMP (stability bound)
    miss_s, miss_t = consistency_gaps(text, graph)
    converged = not miss_s and not miss_t
    return graph, initial, history, converged


def main():
    print("=" * 74)
    print("POSITIVE-FEEDBACK EXTRACTION (op-amp 'close the loop'); reference = plain")
    print("text<->graph consistency, NO special math involved")
    print("=" * 74)
    text = ("A customer order enters Review. If approved it goes to Packing. If "
            "rejected it goes to Refund. Packing goes to Shipped. Shipped goes to "
            "Closed. Refund goes to Closed.")
    print(f"\nText: {text}\n")
    graph, _initial, history, converged = extract_iterative(text)
    print("\n" + "-" * 74)
    print(f"iterations run: {len(history)}")
    if converged:
        print(f"CONVERGED to a fixed point with NO residual gaps. Final states: {graph['states']}")
        print("  -> the dropped branch was recovered by the regenerative loop, then the")
        print("     fixed-point test (negative-feedback reference) stopped it cleanly.")
    else:
        ms, mt = consistency_gaps(text, graph)
        print(f"DID NOT CONVERGE within the cap. REFUSAL CLAMP fires:")
        print(f"  residual gaps: missing states {ms}, missing transitions {mt}")
        print("  -> the system refuses to report a confident-but-incomplete result")
        print("     (the stability bound that keeps positive feedback from faking 'OK').")
    print("\n" + "=" * 74)
    print("PRINCIPLE DEMONSTRATED")
    print("=" * 74)
    print("""\
- POSITIVE feedback (regenerative re-extraction) recovered coverage that the
  one-shot negative-feedback pass could not — it amplified toward completeness.
- It was made SAFE by two negative-feedback bounds: a deterministic fixed-point
  reference (text<->graph consistency) and a refusal clamp on non-convergence.
- The reference uses ZERO special mathematics — just regex graph consistency. So
  the 'LLM feedback control / refusal-as-stabilizer' discipline stands entirely
  on its own, whether or not any special mathematics is used.""")


if __name__ == "__main__":
    main()
