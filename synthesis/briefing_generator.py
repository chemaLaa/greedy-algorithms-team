"""
The actual model call: builds the prompt via prompt_builder, calls the
model, parses the JSON response into a Briefing.

NETWORK / DEPENDENCY LIMITATION — not testable in this sandbox (no
network access here, and the `anthropic` package isn't installed). Every
piece of logic EXCEPT the real API call is tested via a fake client
object that mimics anthropic.Anthropic's interface (see
tests/test_briefing_generator.py) — parsing, error handling, the
markdown-fence-stripping fallback, and the read-time estimate are all
verified without hitting a network. The real call itself (`_default_client()`
building a genuine anthropic.Anthropic() and `generate_briefing()` calling
it with no `client=` override) has NOT been executed here — verify on
your own machine:
    pip install anthropic
    export ANTHROPIC_API_KEY=...
    python3 -c "
from synthesis.briefing_generator import generate_briefing
# build a real context first (see README), then:
briefing = generate_briefing(context)
print(briefing)
"

DEFAULT_MODEL below is set from Anthropic's current model string as of
this writing — double-check it's still valid for your API key before
relying on it; model strings change.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .prompt_builder import build_prompt

DEFAULT_MODEL = "claude-sonnet-5"
# 1024 was tried first and proved too tight in practice — a real model
# response got cut off mid-sentence before finishing the JSON structure
# (three ~150-220 word sections plus JSON syntax overhead adds up).
# 4096 leaves real headroom; still fails loudly and specifically (see the
# stop_reason check in generate_briefing) if a model ever runs long
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
    context: dict, model: str = DEFAULT_MODEL, client=None, max_tokens: int = DEFAULT_MAX_TOKENS
) -> dict:
    """
    context: a BriefingContext (synthesis.context_builder.build_briefing_context() output)
    model: the Anthropic model string to use (see DEFAULT_MODEL note above)
    client: an already-constructed client object exposing
        `.messages.create(model=, max_tokens=, system=, messages=)` and
        returning an object with a `.content` list of blocks each having
        `.type` and `.text`, and a `.stop_reason` attribute — matches
        anthropic.Anthropic()'s interface. Pass one explicitly for custom
        auth/timeout config, for tests (a fake client), or leave None to
        construct a default anthropic.Anthropic() from the
        ANTHROPIC_API_KEY environment variable.
    max_tokens: passed straight through to the API call. Raise this if
        you see a "truncated" BriefingGenerationError (see below) —
        that's the model running out of room mid-response, not a bug in
        this code.

    Returns:
        {
          "recent_development": str,
          "health_check": str,
          "outlook_and_actions": str,
          "read_time_estimate_seconds": int,
          "raw_model_response": str,
        }

    Raises BriefingGenerationError on any failure — API call, a response
    truncated by hitting max_tokens, JSON parsing, or missing required
    keys.
    """
    prompt = build_prompt(context)

    if client is None:
        client = _default_client()

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=prompt["system"],
            messages=prompt["messages"],
        )
    except BriefingGenerationError:
        raise
    except Exception as e:
        raise BriefingGenerationError(f"Model call failed: {e!r}") from e

    stop_reason = getattr(response, "stop_reason", None)
    if stop_reason == "max_tokens":
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
    return result


def _default_client():
    try:
        import anthropic
    except ImportError as e:
        raise BriefingGenerationError(
            "The 'anthropic' package isn't installed — run `pip install anthropic`."
        ) from e

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise BriefingGenerationError("ANTHROPIC_API_KEY environment variable is not set.")

    return anthropic.Anthropic(api_key=api_key)


def _extract_text(response) -> str:
    """
    A response's .content is a list of content blocks; a plain-text
    reply has one block with .text and .type == "text". Concatenates all
    text blocks defensively (skipping any non-text block type) rather
    than assuming exactly one block.
    """
    parts = [
        block.text for block in getattr(response, "content", []) if getattr(block, "type", None) == "text"
    ]
    return "".join(parts)


def _parse_json_response(raw_text: str) -> dict:
    """
    Models sometimes wrap JSON in a markdown code fence (```json ... ```)
    despite being told not to — stripped here before parsing rather than
    failing on a purely cosmetic wrapper.

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