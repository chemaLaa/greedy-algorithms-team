"""
The actual model call: builds the prompt via prompt_builder, calls the
model, parses the JSON response into a Briefing.

Uses OpenAI's Chat Completions API (`client.chat.completions.create()`),
requesting strict JSON mode via `response_format={"type": "json_object"}`
rather than relying on prompt-only instructions — more reliable than hoping
the model remembers not to wrap the JSON in prose or a markdown fence
(though the fence-stripping fallback in _parse_json_response() is kept
regardless, since models still do this occasionally even under JSON mode).

NETWORK / DEPENDENCY LIMITATION: no OPENAI_API_KEY was available where this
was last verified, so the real API call itself (`_default_client()`
building a genuine openai.OpenAI() and `generate_briefing()` calling it with
no `client=` override) has NOT been executed against a live OpenAI account.
Every piece of logic EXCEPT the real API call is tested via a fake client
object that mimics openai.OpenAI()'s interface (see
tests/test_briefing_generator.py) — parsing, error handling, the
markdown-fence-stripping fallback, and the read-time estimate are all
verified without hitting a network. Verify the real call on your own
machine:
    pip install openai
    export OPENAI_API_KEY=...
    python3 -c "
from synthesis.briefing_generator import generate_briefing
# build a real context first (see README), then:
briefing = generate_briefing(context)
print(briefing)
"

DEFAULT_MODEL below is set to a current OpenAI model that supports JSON
mode as of this writing — double-check it's still valid for your API key
before relying on it; model strings change.
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

from .prompt_builder import build_prompt

DEFAULT_MODEL = "gpt-4o"
# 1024 was tried first and proved too tight in practice — a real model
# response got cut off mid-sentence before finishing the JSON structure
# (three ~150-220 word sections plus JSON syntax overhead adds up).
# 4096 leaves real headroom; still fails loudly and specifically (see the
# finish_reason check in generate_briefing) if a model ever runs long
# enough to hit even this.
DEFAULT_MAX_TOKENS = 4096
REQUIRED_KEYS = ("recent_development", "health_check", "outlook_and_actions")

# ~200 words/minute is a commonly cited average adult silent-reading
# speed — used only to produce a rough read_time_estimate_seconds, not a
# precise claim.
WORDS_PER_MINUTE = 200


class BriefingGenerationError(Exception):
    """
    Raised whenever the model call fails or returns something unusable —
    a failed API call, non-JSON output, or JSON missing a required
    section. Deliberately loud: a demo should surface this clearly
    rather than silently show a broken or partial briefing.
    """


def generate_briefing(
    context: dict,
    model: str = DEFAULT_MODEL,
    client=None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_attempts: int = 3,
) -> dict:
    """
    context: a BriefingContext (synthesis.context_builder.build_briefing_context() output)
    model: the OpenAI model string to use (see DEFAULT_MODEL note above)
    client: an already-constructed client object exposing
        `.chat.completions.create(model=, max_tokens=, messages=,
        response_format=)` and returning an object with a `.choices` list
        whose first element has `.message.content` (a plain string) and a
        `.finish_reason` attribute — matches openai.OpenAI()'s interface.
        Pass one explicitly for custom auth/timeout config, for tests (a
        fake client), or leave None to construct a default openai.OpenAI()
        from the OPENAI_API_KEY environment variable.
    max_tokens: passed straight through to the API call. Raise this if
        you see a "truncated" BriefingGenerationError (see below) —
        that's the model running out of room mid-response, not a bug in
        this code.
    max_attempts: retries the full call (not just parsing) up to this
        many times if the model returns malformed/incomplete JSON —
        confirmed necessary in practice: a real run produced valid JSON
        for 3 of 4 clients and, for the 4th, a response missing a
        required key entirely with finish_reason "stop" (i.e. the model
        itself believed it was done) — not a max_tokens truncation,
        genuine occasional unreliability in structured JSON generation. A
        fresh attempt is the standard, effective fix for this failure
        mode. Set to 1 to disable retrying.

    Returns:
        {
          "recent_development": str,
          "health_check": str,
          "outlook_and_actions": str,
          "read_time_estimate_seconds": int,
          "raw_model_response": str,
          "sources": list[dict],  # context["sources"], passed through as-is —
                                  # a code-built audit trail, never written by
                                  # the model (see context_builder.py)
        }

    Raises BriefingGenerationError if every attempt fails — API call, a
    response truncated by hitting max_tokens, JSON parsing, or missing
    required keys. The error message from the LAST attempt is the one
    raised; earlier attempts' failures aren't otherwise surfaced.
    """
    if client is None:
        client = _default_client()

    last_error: Optional[BriefingGenerationError] = None
    for attempt in range(max_attempts):
        started = time.monotonic()
        print(f"[briefing_generator] attempt {attempt + 1}/{max_attempts}: calling model...", flush=True)
        try:
            result = _generate_once(context, model, client, max_tokens)
            elapsed = time.monotonic() - started
            print(f"[briefing_generator] attempt {attempt + 1} succeeded in {elapsed:.1f}s", flush=True)
            return result
        except BriefingGenerationError as e:
            elapsed = time.monotonic() - started
            print(f"[briefing_generator] attempt {attempt + 1} failed after {elapsed:.1f}s: {e}", flush=True)
            last_error = e

    raise last_error


def _generate_once(context: dict, model: str, client, max_tokens: int) -> dict:
    prompt = build_prompt(context)
    messages = [{"role": "system", "content": prompt["system"]}, *prompt["messages"]]

    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
            response_format={"type": "json_object"},
        )
    except BriefingGenerationError:
        raise
    except Exception as e:
        raise BriefingGenerationError(f"Model call failed: {e!r}") from e

    choices = getattr(response, "choices", None) or []
    finish_reason = getattr(choices[0], "finish_reason", None) if choices else None
    if finish_reason == "length":
        raise BriefingGenerationError(
            f"Model response was truncated — it hit the max_tokens limit ({max_tokens}) "
            f"before finishing. This is not a JSON-formatting bug; increase max_tokens "
            f"(generate_briefing(..., max_tokens=...)) and retry. "
            f"Partial response: {_extract_text(response)!r}"
        )

    raw_text = _extract_text(response)
    parsed = _parse_json_response(raw_text)

    missing = [key for key in REQUIRED_KEYS if key not in parsed]
    if missing:
        raise BriefingGenerationError(
            f"Model response missing required key(s) {missing}. Raw response: {raw_text!r}"
        )

    word_count = sum(len(str(parsed[key]).split()) for key in REQUIRED_KEYS)
    read_time_seconds = round(word_count / WORDS_PER_MINUTE * 60)

    result = {key: parsed[key] for key in REQUIRED_KEYS}
    result["read_time_estimate_seconds"] = read_time_seconds
    result["raw_model_response"] = raw_text
    # Passed through verbatim from context_builder's own code-built audit
    # trail — NEVER generated by the model. Asking an LLM to cite its own
    # sources just gets you plausible-looking invented ones; every entry
    # here instead traces back to a fact context_builder can prove it
    # actually received (see synthesis.context_builder._sources_section).
    result["sources"] = context.get("sources", [])
    return result


def _default_client(timeout_seconds: float = 90.0):
    try:
        import openai
    except ImportError as e:
        raise BriefingGenerationError(
            "The 'openai' package isn't installed — run `pip install openai`."
        ) from e

    # Some Python installations (notably python.org builds and certain
    # macOS setups) don't wire SSL certificate verification up to the
    # system trust store the way `curl` does — TLS handshakes then fail
    # or hang entirely, surfacing as a slow APIConnectionError rather
    # than a clear SSL error. Confirmed as the real root cause of a real
    # ~60-75s hang-then-fail in testing (against Anthropic's API, but the
    # same underlying httpx/SSL issue applies to any HTTPS client here).
    # Relying on the user's shell having SSL_CERT_FILE exported is
    # fragile (it doesn't persist across terminal sessions, as happened
    # in practice) — set it here, in code, every time this runs, so it
    # never depends on shell state again.
    try:
        import certifi

        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    except ImportError:
        pass  # certifi not installed — best-effort, fall through to whatever's configured

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise BriefingGenerationError("OPENAI_API_KEY environment variable is not set.")

    return openai.OpenAI(api_key=api_key, timeout=timeout_seconds)


def _extract_text(response) -> str:
    """
    An OpenAI chat completion's `.choices[0].message.content` is already a
    plain string (unlike Anthropic's list-of-content-blocks shape) — this
    just guards against an empty/missing choices list rather than
    assuming there's always exactly one.
    """
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    return getattr(message, "content", None) or ""


def _parse_json_response(raw_text: str) -> dict:
    """
    Models sometimes wrap JSON in a markdown code fence (```json ... ```)
    despite being told not to — and despite JSON mode being requested —
    stripped here before parsing rather than failing on a purely cosmetic
    wrapper.

    strict=False: a model writing multi-paragraph prose inside a JSON
    string value sometimes emits a literal newline character instead of
    an escaped "\\n" — technically invalid JSON (json.loads raises
    "Invalid control character" on this by default), but a real,
    non-rare failure mode for LLM-generated JSON specifically. Python's
    json module's strict=False mode allows raw control characters inside
    strings without otherwise loosening the grammar, which is exactly
    the right trade-off here — confirmed against a real truncated-newline
    response seen in testing.

    Raises BriefingGenerationError (not json.JSONDecodeError) on
    genuinely invalid JSON, so callers only need to catch one exception
    type from this module.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError as e:
        raise BriefingGenerationError(f"Model response was not valid JSON: {raw_text!r}") from e
