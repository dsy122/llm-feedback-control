"""LLM-as-critic controller — deterministic tests with an injected fake model.

No network / no real LLM: every test stubs ``generate`` with a scripted function,
exactly as the rest of the suite does. This proves the controller seam works and
that the critic composes with the deterministic references.
"""
import llm_feedback_control as lfc
from llm_feedback_control import feedback_loop, combine_references, quorum_reference
from llm_feedback_control.critic import (
    llm_critic_reference, llm_critic_repair, _default_similar,
)


def _critic(*gaps):
    """A critic stub that always raises the given gaps."""
    import json
    payload = json.dumps({"gaps": list(gaps)})
    return llm_critic_reference(generate=lambda p, fmt=None, **k: payload)


EXACT = lambda a, b: str(a) == str(b)


def test_critic_reference_parses_gaps():
    def fake(prompt, fmt=None, **kw):
        return '{"gaps": ["missing step Closed", "invented step Foo"]}'
    ref = llm_critic_reference(generate=fake)
    assert ref("source", {"states": ["A"]}) == ["missing step Closed", "invented step Foo"]


def test_critic_reference_empty_when_satisfied():
    def fake(prompt, fmt=None, **kw):
        return '{"gaps": []}'
    assert llm_critic_reference(generate=fake)("t", {"x": 1}) == []


def test_critic_tolerates_messy_reply():
    # model wraps JSON in prose; the parser still recovers the object
    def chatty(prompt, fmt=None, **kw):
        return 'Sure! Here you go:\n{"gaps": ["x"]}\nHope that helps.'
    assert llm_critic_reference(generate=chatty)("t", {}) == ["x"]


def test_critic_degrades_without_model():
    def dead(prompt, fmt=None, **kw):
        raise lfc.BackendError("no backend")
    # cannot critique -> no gaps, no crash (keep a deterministic ref if this
    # silent pass is not acceptable)
    assert llm_critic_reference(generate=dead)("t", {"x": 1}) == []


def test_critic_loop_converges():
    """A model in the controller seat drives the loop to a fixed point: the
    critic complains until 'severity' is present, repair adds it, critic clears."""
    def scripted(prompt, fmt=None, **kw):
        if "Revise" in prompt:
            return '{"title": "x", "severity": "high"}'
        return '{"gaps": []}' if '"severity"' in prompt else '{"gaps": ["severity missing"]}'

    cand, initial, hist, conv = feedback_loop(
        "incident severity high",
        extract=lambda t: {"title": "x"},
        reference=llm_critic_reference(generate=scripted),
        repair=llm_critic_repair(generate=scripted),
        signature=lambda c: tuple(sorted(c.items())),
        max_iters=4)
    assert conv is True
    assert cand.get("severity") == "high"
    assert initial == {"title": "x"}


def test_critic_loop_refuses_when_unfixable():
    """If the critic never clears, the refusal clamp fires (converged False) —
    the loop does not report a confident-but-unsatisfied result."""
    def stubborn(prompt, fmt=None, **kw):
        if "Revise" in prompt:
            return '{"title": "x"}'          # repair changes nothing useful
        return '{"gaps": ["still wrong"]}'   # critic never satisfied
    _, _, _, conv = feedback_loop(
        "t", extract=lambda t: {"title": "x", "n": 0},
        reference=llm_critic_reference(generate=stubborn),
        repair=lambda t, c, g: {"title": "x", "n": c["n"] + 1},  # always changes
        signature=lambda c: c["n"], max_iters=3)
    assert conv is False


def test_combine_keeps_exact_floor():
    """combine_references is a summing junction: the loop converges only when the
    exact reference AND the critic are both satisfied."""
    def exact_ref(t, c):
        return [] if c.get("done") else [("exact", "not done")]
    happy = llm_critic_reference(generate=lambda p, fmt=None, **kw: '{"gaps": []}')
    grumpy = llm_critic_reference(generate=lambda p, fmt=None, **kw: '{"gaps": ["meh"]}')

    # exact not satisfied -> the exact gap is reported regardless of the critic
    assert combine_references(exact_ref, happy)("t", {"done": False}) == [("exact", "not done")]
    # exact satisfied + critic happy -> converged (no gaps)
    assert combine_references(exact_ref, happy)("t", {"done": True}) == []
    # exact satisfied but critic unhappy -> still a gap (floor passed, breadth added)
    assert combine_references(exact_ref, grumpy)("t", {"done": True}) == ["meh"]


def test_combine_dedups():
    a = lambda t, c: ["g", "h"]
    b = lambda t, c: ["h", "i"]
    assert combine_references(a, b)("t", {}) == ["g", "h", "i"]
    assert combine_references(a, b, dedup=False)("t", {}) == ["g", "h", "h", "i"]


# --- quorum_reference (the instrumentation amp) --------------------------------
def test_quorum_keeps_agreed_rejects_idiosyncratic():
    a = _critic("X missing", "noise A")
    b = _critic("X missing", "noise B")
    ref = quorum_reference(a, b, quorum=2, similar=EXACT)
    assert ref("t", {}) == ["X missing"]           # private noise rejected


def test_quorum_one_is_union():
    a, b = _critic("g1"), _critic("g2")
    assert sorted(quorum_reference(a, b, quorum=1, similar=EXACT)("t", {})) == ["g1", "g2"]


def test_quorum_unanimous_needs_all():
    a, b, c = _critic("shared", "only-a"), _critic("shared"), _critic("shared", "only-c")
    assert quorum_reference(a, b, c, quorum=3, similar=EXACT)("t", {}) == ["shared"]


def test_quorum_clamped_and_empty():
    a = _critic("g")
    # quorum > n is clamped to n (unanimous); a lone critic still counts
    assert quorum_reference(a, quorum=5, similar=EXACT)("t", {}) == ["g"]
    assert quorum_reference(quorum=1)("t", {}) == []          # no critics -> no gaps


def test_default_similar_matches_paraphrase_separates_distinct():
    assert _default_similar("the severity field is missing", "severity value is missing")
    assert not _default_similar("severity is missing", "owner team is unclear")


def test_instrumentation_loop_converges_on_agreed_issue():
    """Two independent critics; only the agreed issue (severity) drives repair,
    each critic's private noise is rejected, and the loop reaches a fixed point."""
    def critic_a(p, fmt=None, **k):
        return '{"gaps": []}' if '"severity"' in p else \
               '{"gaps": ["the severity field is missing", "capitalize the title"]}'
    def critic_b(p, fmt=None, **k):
        return '{"gaps": []}' if '"severity"' in p else \
               '{"gaps": ["severity value is missing", "owner team unclear"]}'
    def repair_model(p, fmt=None, **k):
        return '{"title": "x", "severity": "high"}'

    ref = quorum_reference(llm_critic_reference(generate=critic_a),
                           llm_critic_reference(generate=critic_b), quorum=2)
    cand, initial, hist, conv = feedback_loop(
        "incident severity high",
        extract=lambda t: {"title": "x"},
        reference=ref, repair=llm_critic_repair(generate=repair_model),
        signature=lambda c: tuple(sorted(c.items())), max_iters=4)
    assert conv is True
    assert cand.get("severity") == "high"
