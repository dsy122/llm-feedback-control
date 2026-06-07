"""LLM-as-critic feedback control — a *model* in the controller seat.

The deterministic references in this package (``consistency_gaps``,
``form_field_gaps``) are EXACT: they can only express what code can check, but
whatever they check, they check with a guarantee. This module adds the other
controller the op-amp analogy allows — a low-power LLM acting as the *critic* in
the feedback loop. It widens what the loop can react to (relevance, coherence,
"did it actually answer the question" — things no rule captures) at a price the
rest of the package is careful to avoid: the critic is an ESTIMATE, not a
guarantee. It can pass a bad answer and fail a good one.

So the intended use is HYBRID, not replacement. Keep a deterministic reference
as the floor (the things that must be right, and the refusal), and add a critic
on top for the fuzzy quality dimensions::

    from llm_feedback_control import feedback_loop, combine_references
    from llm_feedback_control.critic import llm_critic_reference, llm_critic_repair

    reference = combine_references(exact_reference, llm_critic_reference(generate))
    cand, initial, history, converged = feedback_loop(
        text, extract=extract, reference=reference,
        repair=llm_critic_repair(generate), signature=signature)

Two cautions, both load-bearing:

  * **Independence.** A critic that shares the generator's blind spots — above
    all, the *same* model — rubber-stamps its own mistakes (the correlated-error
    trap). Use a different, ideally independent, small model for the critic
    (pass ``model=`` or a separate ``generate``).
  * **No guarantee.** The loop still terminates only because of ``max_iters`` and
    the refusal clamp — not because the critic is sound. Anything that must be
    correct belongs in the deterministic reference, not the critic.

Zero third-party dependencies; the model is injected via ``generate`` exactly as
elsewhere in the package.
"""
import json
import re

from .llm import gen, BackendError
from .loop import feedback_loop


def _parse_json(s):
    """Best-effort parse of a model's reply: straight JSON first, then the first
    ``{...}`` block. Returns a dict, or ``{}`` on failure (never raises)."""
    if isinstance(s, (dict, list)):
        return s
    try:
        return json.loads(s)
    except Exception:
        pass
    m = re.search(r"\{.*\}", s or "", re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {}


def llm_critic_reference(generate=None, *, rubric=None, model=None,
                         max_gaps=8, verbose=False):
    """Build a feedback ``reference`` whose controller is a low-power LLM.

    The returned callable has the loop's reference signature
    ``reference(text, candidate) -> gaps``. It asks the model to critique the
    candidate against the source text (and an optional ``rubric``) and return a
    list of SPECIFIC, checkable deficiencies. An empty list means the critic is
    satisfied — the loop's fixed point on the fuzzy dimension. Each gap is a
    short string.

    If the model is unreachable or its reply will not parse, the critic returns
    NO gaps (it cannot critique, so it does not block). Keep a deterministic
    reference alongside it (see :func:`combine_references`) if "no model" must
    not silently pass. ``rubric`` is appended to the prompt to focus the
    critique; ``model`` overrides the model name on the default backend.

    NOTE: an *estimated* controller — see the module docstring.
    """
    g = generate or gen                       # injected model, or the package default

    def reference(text, candidate):
        # Serialise the candidate so the model can see exactly what it is judging.
        # default=str keeps non-JSON values (dates, etc.) from blowing up.
        cand_json = json.dumps(candidate, default=str, ensure_ascii=False)
        rub = f"\nJudge specifically against: {rubric}" if rubric else ""
        # Ask for problems ONLY (not a rewrite): the loop's repair step does the
        # rewriting. An empty list is the critic's "satisfied" — the fixed point.
        prompt = (
            "You are a strict reviewer. Compare the CANDIDATE answer to the "
            "SOURCE text and list specific, checkable problems with the "
            "candidate: anything missing, invented, or wrong. Do not rewrite it; "
            "only list problems. If it is faithful and complete, return an empty "
            'list. Return ONLY JSON {"gaps": ["...", ...]}.' + rub +
            f"\nSOURCE: {text}\nCANDIDATE: {cand_json}")
        try:
            data = _parse_json(g(prompt, fmt="json", model=model) if model
                               else g(prompt, fmt="json"))
        except BackendError:
            # No model reachable: the critic cannot judge, so it raises NO gaps
            # (it must not block). Pair it with a deterministic reference via
            # combine_references if a missing model must not silently pass.
            if verbose:
                print("  [critic] no backend reachable -> no gaps (cannot critique)")
            return []
        except Exception:
            return []                          # any model/parse error -> no gaps
        # Normalise the reply to a clean, bounded list of non-empty strings.
        gaps = data.get("gaps", []) if isinstance(data, dict) else []
        gaps = [str(x).strip() for x in gaps if str(x).strip()][:max_gaps]
        if verbose:
            print(f"  [critic] {len(gaps)} issue(s): {gaps}")
        return gaps

    return reference


def llm_critic_repair(generate=None, *, model=None):
    """Build a ``repair`` that asks the model to revise the candidate to address
    the critic's gaps, returning a corrected object of the SAME JSON shape.

    Returns the parsed correction, or ``None`` if the model is unreachable or
    the reply will not parse — which stops the loop and, if gaps remain, fires
    the refusal clamp."""
    g = generate or gen

    def repair(text, candidate, gaps):
        cand_json = json.dumps(candidate, default=str, ensure_ascii=False)
        issues = "; ".join(str(x) for x in gaps)        # the critic's gap list
        # Re-ask the model to FIX the listed problems and return the same shape,
        # so the loop can re-check the result and either converge or refuse.
        prompt = (
            "Revise the CANDIDATE to fix the listed PROBLEMS, staying faithful to "
            "the SOURCE. Return ONLY the corrected answer as JSON of the same "
            "shape as the candidate.\n"
            f"SOURCE: {text}\nCANDIDATE: {cand_json}\nPROBLEMS: {issues}")
        try:
            data = _parse_json(g(prompt, fmt="json", model=model) if model
                               else g(prompt, fmt="json"))
        except Exception:
            return None                  # can't repair -> stop; loop may then refuse
        return data or None              # empty/garbage parse -> treat as "no repair"

    return repair


def combine_references(*references, dedup=True):
    """Compose several feedback references into one.

    The combined reference reports the concatenation of every sub-reference's
    gaps, so the loop converges only when ALL of them are satisfied. Put the
    deterministic (exact) reference FIRST and a critic SECOND to keep the hard
    guarantee as the floor and add the critic's breadth on top::

        reference = combine_references(exact_reference, llm_critic_reference(gen))

    With ``dedup=True`` (default), repeated gaps (by string form) are dropped,
    order preserved."""
    def reference(text, candidate):
        out, seen = [], set()
        for ref in references:
            for gap in ref(text, candidate):
                key = repr(gap)
                if dedup and key in seen:
                    continue
                seen.add(key)
                out.append(gap)
        return out

    return reference


_STOP = {"the", "and", "for", "with", "that", "this", "are", "was", "but",
         "not", "has", "have", "its", "you", "your", "then", "they", "them",
         "there", "here", "should", "would", "could", "also", "into", "from",
         "than", "when", "what", "which", "been", "being"}


def _norm_tokens(s):
    """Content words of a gap string: lowercase alphanumerics, length >= 3, with
    common function words dropped."""
    return {t for t in re.findall(r"[a-z0-9]+", str(s).lower())
            if len(t) >= 3 and t not in _STOP}


def _default_similar(a, b, thresh=0.4):
    """Crude, dependency-free "same issue?" test for two free-text gaps: Jaccard
    overlap of content words >= ``thresh``, or one normalised form contained in
    the other. Good enough to cluster close paraphrases; for production, inject a
    stronger ``similar`` (embeddings, or an LLM judge) into :func:`quorum_reference`."""
    ta, tb = _norm_tokens(a), _norm_tokens(b)
    if not ta or not tb:
        return str(a).strip().lower() == str(b).strip().lower()
    if len(ta & tb) / len(ta | tb) >= thresh:
        return True
    sa, sb = " ".join(sorted(ta)), " ".join(sorted(tb))
    return sa in sb or sb in sa


def quorum_reference(*references, quorum=None, similar=None, verbose=False):
    """The instrumentation amp: combine references by AGREEMENT, not by sum.

    Where :func:`combine_references` is a summing junction (it reports the union
    of every reference's gaps), this reports only the gaps that **at least
    ``quorum`` references independently raise**. Gaps that a single reference
    raises on its own are rejected as noise — the common-mode rejection of
    per-critic idiosyncrasy.

    Its whole value rests on the references being **independent** — above all,
    *different models*. Two critics that are the same model agree trivially and
    reject nothing useful; the point is to keep only what genuinely independent
    observers converge on. (``combine_references`` is the ``quorum=1`` extreme;
    unanimous is ``quorum = number of references``.)

    ``quorum`` defaults to a majority; it is clamped to ``[1, n]``. ``similar``
    decides when two free-text gaps are "the same issue" (default
    :func:`_default_similar`); inject a stronger matcher for production.

    The precision/recall trade-off is explicit and yours to tune: a high quorum
    rejects more noise but can miss a real issue only one critic caught."""
    refs = list(references)
    n = len(refs)
    sim = similar or _default_similar

    def reference(text, candidate):
        if n == 0:
            return []
        q = quorum if quorum is not None else (n // 2 + 1)
        q = max(1, min(q, n))
        clusters = []                       # each: {"rep": gap, "critics": set}
        for ci, ref in enumerate(refs):
            for gap in ref(text, candidate):
                target = next((c for c in clusters if sim(gap, c["rep"])), None)
                if target is None:
                    clusters.append({"rep": gap, "critics": {ci}})
                else:
                    target["critics"].add(ci)
        kept = [c["rep"] for c in clusters if len(c["critics"]) >= q]
        if verbose:
            for c in clusters:
                s = len(c["critics"])
                print(f"  [quorum {s}/{n}] {'KEEP  ' if s >= q else 'reject'} "
                      f"{c['rep']!r}")
        return kept

    return reference


def _demo():
    """Self-contained, OFFLINE demonstration — a scripted 'model' so the loop is
    visible with no Ollama. The critic flags a field the source states but the
    candidate dropped; repair adds it; the critic then clears and the loop
    reaches a fixed point."""
    def scripted(prompt, fmt=None, **kw):
        if "Revise" in prompt:                       # repair call
            return '{"title": "Q3 outage", "owner": "ops", "severity": "high"}'
        if '"severity"' in prompt:                   # critic: candidate now complete
            return '{"gaps": []}'
        return '{"gaps": ["the source states severity \\"high\\" but it is missing"]}'

    text = "Incident: Q3 outage, owned by ops, severity high."
    print("=" * 74)
    print("LLM-AS-CRITIC FEEDBACK CONTROL (offline scripted model)")
    print("=" * 74)
    print(f"\nSOURCE: {text}\n")
    cand, initial, history, converged = feedback_loop(
        text,
        extract=lambda t: {"title": "Q3 outage", "owner": "ops"},   # drops 'severity'
        reference=llm_critic_reference(generate=scripted, verbose=True),
        repair=llm_critic_repair(generate=scripted),
        signature=lambda c: tuple(sorted(c.items())),
        max_iters=4, verbose=True, label="critic")
    print(f"\ninitial  (open-loop): {initial}")
    print(f"final    (closed-loop): {cand}")
    print(f"converged: {converged}")
    print("\n" + "-" * 74)
    print("The controller here is a MODEL, not exact code: it widened what the loop\n"
          "could react to (a missing field no rule was written for). Keep a\n"
          "deterministic reference alongside it for anything that must be guaranteed.")


def _demo_instrumentation():
    """Two INDEPENDENT critics (pretend different models). Each catches the real
    issue but also raises its own idiosyncratic noise. quorum=2 keeps only what
    BOTH agree on; each critic's private complaint is common-mode-rejected."""
    def critic_a(prompt, fmt=None, **kw):
        if '"severity"' in prompt:
            return '{"gaps": []}'
        return ('{"gaps": ["the severity field is missing", '
                '"consider capitalizing the title"]}')

    def critic_b(prompt, fmt=None, **kw):
        if '"severity"' in prompt:
            return '{"gaps": []}'
        return '{"gaps": ["severity value is missing", "owner team is unclear"]}'

    def repair_model(prompt, fmt=None, **kw):
        return '{"title": "Q3 outage", "owner": "ops", "severity": "high"}'

    reference = quorum_reference(
        llm_critic_reference(generate=critic_a),
        llm_critic_reference(generate=critic_b),
        quorum=2, verbose=True)

    text = "Incident: Q3 outage, owned by ops, severity high."
    print("=" * 74)
    print("INSTRUMENTATION AMP: two independent critics, common-mode rejection")
    print("=" * 74)
    print(f"\nSOURCE: {text}\n")
    cand, initial, history, converged = feedback_loop(
        text, extract=lambda t: {"title": "Q3 outage", "owner": "ops"},
        reference=reference, repair=llm_critic_repair(generate=repair_model),
        signature=lambda c: tuple(sorted(c.items())), max_iters=4, verbose=True,
        label="instr")
    print(f"\ninitial: {initial}\nfinal  : {cand}\nconverged: {converged}")
    print("\nOnly the issue BOTH critics raised (severity) drove a repair; each\n"
          "critic's private complaint was rejected as noise. Independence is the\n"
          "common-mode rejection — same-model critics would share blind spots.")


if __name__ == "__main__":
    _demo()
    print()
    _demo_instrumentation()
