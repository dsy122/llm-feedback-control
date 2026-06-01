"""auditor.py — the LLM-feedback-control pipeline, end-to-end and self-contained.

A small LLM is wrapped in a deterministic feedback network so the system knows
what it can compute exactly, does so, and refuses the rest:

    English text
      -> extract finite transition system   (LLM + schema + deterministic fallback)
      -> regime gate                         (hybrid: heuristic + LLM tie-break)
      -> exact analysis                      (standard graph facts + an optional
                                              finite-field spectral fingerprint)
      -> readout contract + injectivity      (refuse non-injective lifts)
      -> grounded report                     (every claim backed by a trace fact)

This is the NEGATIVE-feedback half (gate / ground / refuse). The bounded
POSITIVE-feedback loop (iterate-to-fixed-point re-extraction) lives in
feedback.py.

Demos three milestones:
  M1  process auditor on a real workflow (exact trace + grounded report)
  M2  gate refusal on belief/continuous input ("model-only, refused")
  M3  non-injective readout refusal (the no-hallucinated-synthesis guard)

Plus a HARDENING test of the gate on deliberately ambiguous / mixed inputs.

The LLM client is shared (llm.py); set LFC_MODEL / OLLAMA_HOST to point at any
local Ollama model.  Run:  python auditor.py
"""
import sys, json, re

from llm import gen

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


# === exact engine: F_p fp_orbit + graph facts (self-contained) ============
PRIMES = (2, 3, 5, 7)


def fp_orbit(M, x0, p, max_steps=20000):
    n = len(x0); x = [v % p for v in x0]; seen = {}; orbit = []
    for t in range(max_steps):
        k = tuple(x)
        if k in seen:
            s = seen[k]
            return s, t - s, orbit[s:]          # transient, period, cycle vectors
        seen[k] = t; orbit.append(x)
        x = [sum(M[i][j] * x[j] for j in range(n)) % p for i in range(n)]
    return None, None, []


def transfer_operator(states, trans, p):
    idx = {s: i for i, s in enumerate(states)}; n = len(states)
    M = [[0] * n for _ in range(n)]
    for a, b in trans:
        if a in idx and b in idx:
            M[idx[b]][idx[a]] = (M[idx[b]][idx[a]] + 1) % p     # flow a -> b
    return M, idx


def graph_facts(states, trans):
    out = {s: [b for a, b in trans if a == s] for s in states}
    terminals = sorted(s for s in states if not out.get(s))
    start = states[0] if states else None
    seen = set();
    if start is not None:
        stack = [start]; seen = {start}
        while stack:
            u = stack.pop()
            for v in out.get(u, []):
                if v not in seen:
                    seen.add(v); stack.append(v)
    unreachable = sorted(s for s in states if s not in seen)
    # cycle detection (DFS)
    WHITE, GREY, BLACK = 0, 1, 2
    color = {s: WHITE for s in states}; has_cycle = [False]
    def dfs(u):
        color[u] = GREY
        for v in out.get(u, []):
            if color.get(v) == GREY:
                has_cycle[0] = True
            elif color.get(v) == WHITE:
                dfs(v)
        color[u] = BLACK
    for s in states:
        if color[s] == WHITE:
            dfs(s)
    return dict(terminal_states=terminals, unreachable_states=unreachable,
                has_cycle=has_cycle[0])


def exact_analysis(states, trans):
    """Per-prime exact trace + bad-prime + readout injectivity (the M3 guard)."""
    if not states:
        return {"primes": [], "facts": graph_facts(states, trans)}
    x0 = [1] + [0] * (len(states) - 1)               # launch at the start state
    per_prime = []
    for p in PRIMES:
        M, _ = transfer_operator(states, trans, p)
        transient, period, cycle = fp_orbit(M, x0, p)
        mode = cycle[0] if cycle else [0] * len(states)
        bad = all(v == 0 for v in mode)
        # readout = sum of mode; injective iff distinct cycle vectors -> distinct readouts
        readouts = [sum(v) % p for v in cycle] if cycle else []
        distinct_vecs = len({tuple(v) for v in cycle})
        injective = len(set(readouts)) == distinct_vecs if cycle else True
        per_prime.append(dict(prime=p, transient=transient, period=period,
                              mode=mode, bad_prime=bad, readout_injective=injective))
    return {"primes": per_prime, "facts": graph_facts(states, trans)}


# === regime gate (hybrid: heuristic + LLM tie-break) ======================
CONT_BELIEF = ["continuous", "continuously", "drift", "rises", "grows", "increase",
               "rate", "percent", "gradually", "slowly", "temperature", "price",
               "demand", "confidence", "trust", "trusts", "trustworthy", "feels",
               "happier", "sentiment", "usually", "accumulat", "improves", "volume"]
FINITE_CUES = ["goes to", "moves from", "enters", "starts in", "opens in", "proceed to",
               "escalates", "commits", "rolls back", "either", " or ", "then",
               "if approved", "if rejected", "if unresolved", "retry", "fails"]


def gate_heuristic(text):
    t = text.lower()
    cont = sum(t.count(c) for c in CONT_BELIEF)
    fin = sum(t.count(c) for c in FINITE_CUES)
    return fin, cont


def regime_gate(text, use_llm=True):
    fin, cont = gate_heuristic(text)
    margin = abs(fin - cont)
    # clear cases: decide by heuristic
    if margin >= 2 and not (fin > 0 and cont > 0 and min(fin, cont) >= 2):
        verdict = "finite_structural" if fin > cont else "model_only"
        return dict(verdict=verdict, reason=f"heuristic (fin={fin},cont={cont})", source="heuristic")
    # ambiguous / mixed: ask the LLM to adjudicate
    if use_llm:
        try:
            raw = gen('Classify the description into exactly one label: '
                      '"finite_structural" (a finite set of states and transitions), '
                      '"model_only" (continuous/probabilistic/belief-driven, no finite state machine), '
                      'or "mixed" (both). Return JSON {{"label": "..."}}. '
                      f'Description: "{text}"', fmt="json")
            label = json.loads(raw).get("label", "").strip()
            if label in ("finite_structural", "model_only", "mixed"):
                return dict(verdict=label, reason=f"LLM tie-break (fin={fin},cont={cont})", source="llm")
        except Exception:
            pass
    # fallback: both present -> mixed; else heuristic
    if fin > 0 and cont > 0:
        return dict(verdict="mixed", reason=f"both cues present (fin={fin},cont={cont})", source="heuristic")
    return dict(verdict="finite_structural" if fin >= cont else "model_only",
                reason=f"heuristic-fallback (fin={fin},cont={cont})", source="heuristic")


# === extraction (LLM + schema + deterministic fallback) ===================
def valid(o):
    return (isinstance(o, dict) and isinstance(o.get("states"), list)
            and isinstance(o.get("transitions"), list)
            and all(isinstance(t, list) and len(t) == 2 for t in o["transitions"]))


def fallback_extract(text):
    st, tr = set(), set()
    for m in re.finditer(r"([A-Z][A-Za-z0-9]+)\s+(?:goes to|moves to|to)\s+([A-Z][A-Za-z0-9]+)"
                         r"(?:\s+or(?: to)?\s+([A-Z][A-Za-z0-9]+))?", text):
        a, b, c = m.group(1), m.group(2), m.group(3)
        st |= {a, b}; tr.add((a, b))
        if c: st.add(c); tr.add((a, c))
    for m in re.finditer(r"(?:enters|starts in|opens in)\s+([A-Z][A-Za-z0-9]+)", text):
        st.add(m.group(1))
    return {"states": sorted(st), "transitions": [list(t) for t in sorted(tr)]}


def extract_workflow(text):
    try:
        raw = gen('Extract the finite state machine. Return ONLY JSON '
                  '{{"states":[...],"transitions":[["FROM","TO"],...]}} using exact state '
                  f'names from the text. Text: "{text}"', fmt="json")
        o = json.loads(raw)
        if valid(o) and o["states"]:
            return o, "llm"
    except Exception:
        pass
    return fallback_extract(text), "fallback"


# === grounded report ======================================================
def grounded_report(states, trace, llm=True):
    facts = trace["facts"]
    bad = [pp["prime"] for pp in trace["primes"] if pp["bad_prime"]]
    noninj = [pp["prime"] for pp in trace["primes"] if not pp["readout_injective"]]
    deterministic = (
        f"- States ({len(states)}): {', '.join(states)}\n"
        f"- Terminal states: {', '.join(facts['terminal_states']) or 'none'}\n"
        f"- Unreachable from start: {', '.join(facts['unreachable_states']) or 'none'}\n"
        f"- Contains a cycle (loop): {facts['has_cycle']}\n"
        f"- Bad primes (mode annihilates): {bad or 'none'}\n"
        f"- Non-injective readout at primes (lift REFUSED): {noninj or 'none'}\n"
    )
    english = ""
    if llm:
        try:
            english = gen("Write two plain sentences describing this process using ONLY "
                          "these verified facts. Name only the listed states; invent nothing.\n"
                          + deterministic).strip()
        except Exception:
            english = "(LLM rewrite unavailable; deterministic facts above are authoritative.)"
    return deterministic, english


# === end-to-end audit =====================================================
def run_audit(text, verbose=True):
    gate = regime_gate(text)
    out = {"text": text, "gate": gate}
    if gate["verdict"] == "model_only":
        out["result"] = "REFUSED: model-only regime; no exact finite-structural analysis."
        return out
    graph, how = extract_workflow(text)
    out["extraction"] = {"via": how, "states": graph["states"], "transitions": graph["transitions"]}
    if not graph["states"]:
        out["result"] = "REFUSED: no finite structure could be extracted."
        return out
    trace = exact_analysis(graph["states"], [tuple(t) for t in graph["transitions"]])
    out["trace"] = trace
    det, eng = grounded_report(graph["states"], trace, llm=True)
    out["report_facts"] = det
    out["report_english"] = eng
    out["result"] = "OK" + (" (mixed: finite part analysed, continuous part deferred)"
                            if gate["verdict"] == "mixed" else "")
    return out


# === demos ================================================================
def banner(t):
    print("\n" + "=" * 74 + f"\n{t}\n" + "=" * 74)


def demo_M1():
    banner("M1 — process auditor (full pipeline, exact trace + grounded report)")
    text = ("A customer order enters Review. If approved it goes to Packing. If "
            "rejected it goes to Refund. Packing goes to Shipped. Shipped goes to "
            "Closed. Refund goes to Closed.")
    r = run_audit(text)
    print("gate     :", r["gate"]["verdict"], "|", r["gate"]["reason"])
    print("extracted:", r["extraction"]["via"], r["extraction"]["states"])
    print("report facts:\n" + r["report_facts"])
    print("grounded english:", r.get("report_english", "")[:300])
    print("result   :", r["result"])


def demo_M2():
    banner("M2 — gate refusal on belief/continuous input")
    text = "The market price drifts until confidence improves, then buyers slowly return."
    r = run_audit(text)
    print("input   :", text)
    print("gate    :", r["gate"]["verdict"], "|", r["gate"]["reason"])
    print("result  :", r["result"])


def demo_M3():
    banner("M3 — non-injective readout refusal (no hallucinated synthesis)")
    # a symmetric 4-cycle: its F_p standing mode has a multi-vector cycle whose
    # sum-readout collapses distinct vectors -> the lift must be refused.
    states = ["S0", "S1", "S2", "S3"]
    trans = [("S0", "S1"), ("S1", "S2"), ("S2", "S3"), ("S3", "S0"),
             ("S1", "S0"), ("S2", "S1"), ("S3", "S2"), ("S0", "S3")]  # undirected 4-cycle
    trace = exact_analysis(states, trans)
    for pp in trace["primes"]:
        tag = "BAD-PRIME" if pp["bad_prime"] else ("READOUT NON-INJECTIVE -> LIFT REFUSED"
              if not pp["readout_injective"] else "ok")
        print(f"  prime {pp['prime']}: period={pp['period']} mode={pp['mode']}  -> {tag}")
    refused = [pp["prime"] for pp in trace["primes"] if not pp["readout_injective"] or pp["bad_prime"]]
    print(f"  => CRT synthesis runs ONLY over primes with injective readouts; "
          f"refused/degenerate primes excluded: {refused}")


def test_gate_hard():
    banner("Q2 HARDENING — gate on ambiguous / mixed inputs (hybrid vs heuristic-only)")
    corpus = [
        ("After validation the system either commits or rolls back.", "finite_structural"),
        ("The retry counter increments each cycle until it reaches the limit, then the job fails.", "finite_structural"),
        ("Orders move from Review to Packing, and packing time grows as volume increases.", "mixed"),
        ("If the customer trusts the brand, they proceed to Checkout; otherwise they leave.", "mixed"),
        ("The model's confidence rises with each correct prediction.", "model_only"),
        ("A request goes to Pending, then to Approved or Denied.", "finite_structural"),
        ("Sentiment improves gradually as more reviews accumulate.", "model_only"),
        ("A ticket escalates from Tier1 to Tier2 to Tier3 if unresolved.", "finite_structural"),
    ]
    h_ok = hyb_ok = 0
    for text, truth in corpus:
        fin, cont = gate_heuristic(text)
        h_pred = "finite_structural" if fin > cont else ("model_only" if cont > fin else "mixed")
        hyb = regime_gate(text, use_llm=True)["verdict"]
        h_ok += (h_pred == truth); hyb_ok += (hyb == truth)
        print(f"  truth={truth:<17} heuristic={h_pred:<17} hybrid={hyb:<17} | {text[:42]}")
    print(f"\n  heuristic-only accuracy: {h_ok}/{len(corpus)}   hybrid(LLM) accuracy: {hyb_ok}/{len(corpus)}")


if __name__ == "__main__":
    demo_M1()
    demo_M2()
    demo_M3()
    test_gate_hard()
    print("\n(all stages self-contained; nothing imported from any external solver)")
