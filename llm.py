"""Shared LLM client for the llm-feedback-control project.

Two backends, both behind a tiny interface:
  * gen()         — a local Ollama model (default phi3:mini, the "small model")
  * gen_ceiling() — a stronger reference model: a larger Ollama model OR the
                    OpenAI API (used only as a quality CEILING in experiments)

Everything is configurable by environment variable so the same code runs
locally and on a remote box (e.g. EC2) without edits:

  OLLAMA_HOST   default http://localhost:11434
  LFC_MODEL     default phi3:mini            (the small model under test)
  LFC_CEILING   default llama3.1:8b          (a bigger local Ollama model)
  CEILING_BACKEND  "ollama" (default) or "openai"
  OPENAI_API_KEY   required iff CEILING_BACKEND=openai
  OPENAI_MODEL  default gpt-4o-mini

Only the stdlib is used (urllib + json) — no SDK dependency.
"""
import os
import json
import urllib.request

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
MODEL = os.environ.get("LFC_MODEL", "phi3:mini")
CEILING_MODEL = os.environ.get("LFC_CEILING", "llama3.1:8b")
CEILING_BACKEND = os.environ.get("CEILING_BACKEND", "ollama")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def gen(prompt, fmt=None, model=None, timeout=600):
    """Generate from a local Ollama model. `fmt="json"` forces valid JSON.
    Greedy decode (temperature 0) for reproducibility."""
    body = {"model": model or MODEL, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.0}}
    if fmt:
        body["format"] = fmt
    req = urllib.request.Request(f"{OLLAMA_HOST}/api/generate",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read()).get("response", "")


def _gen_openai(prompt, model=None, timeout=120):
    key = os.environ["OPENAI_API_KEY"]
    body = {"model": model or OPENAI_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0, "response_format": {"type": "json_object"}}
    req = urllib.request.Request("https://api.openai.com/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


def gen_ceiling(prompt, fmt="json", timeout=600):
    """Generate from the CEILING model (a stronger reference). Backend chosen by
    CEILING_BACKEND: a bigger local Ollama model, or the OpenAI API."""
    if CEILING_BACKEND == "openai":
        return _gen_openai(prompt, timeout=timeout)
    return gen(prompt, fmt=fmt, model=CEILING_MODEL, timeout=timeout)


def info():
    return (f"small={MODEL} @ {OLLAMA_HOST} | ceiling={CEILING_MODEL} "
            f"(backend={CEILING_BACKEND})")
