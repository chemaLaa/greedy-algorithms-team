import json
import os

from synthesis.briefing_generator import (
    generate_briefing,
    BriefingGenerationError,
    _default_client,
    _extract_text,
    _parse_json_response,
)


class _FakeTextBlock:
    def __init__(self, text, block_type="text"):
        self.text = text
        self.type = block_type


class _FakeResponse:
    def __init__(self, blocks, stop_reason="end_turn"):
        self.content = blocks
        self.stop_reason = stop_reason


class _FakeMessages:
    def __init__(self, response_text=None, raise_error=None, stop_reason="end_turn", response_sequence=None):
        self._response_text = response_text
        self._raise_error = raise_error
        self._stop_reason = stop_reason
        self._response_sequence = response_sequence  # list of (text, stop_reason) tuples, consumed in order
        self.last_call_kwargs = None
        self.call_count = 0

    def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        self.call_count += 1
        if self._raise_error is not None:
            raise self._raise_error
        if self._response_sequence is not None:
            text, stop_reason = self._response_sequence[self.call_count - 1]
            return _FakeResponse([_FakeTextBlock(text)], stop_reason=stop_reason)
        return _FakeResponse([_FakeTextBlock(self._response_text)], stop_reason=self._stop_reason)


class _FakeClient:
    def __init__(self, response_text=None, raise_error=None, stop_reason="end_turn", response_sequence=None):
        self.messages = _FakeMessages(
            response_text=response_text,
            raise_error=raise_error,
            stop_reason=stop_reason,
            response_sequence=response_sequence,
        )


VALID_JSON_RESPONSE = json.dumps(
    {
        "recent_development": "The portfolio declined slightly this month, driven mainly by weakness in its largest equity holding.",
        "health_check": "One concentrated position exceeds twenty percent of the portfolio.",
        "outlook_and_actions": "Consider discussing rebalancing options with the client on the call.",
    }
)


def _minimal_context():
    return {
        "client": {"name": "Anna Meier", "risk_profile": "Balanced", "esg_profile": None},
        "portfolio": {
            "portfolio_id": 1,
            "portfolio_name": "Vorsorge Indiv",
            "value": 500000,
            "reporting_currency": "CHF",
            "performance_trend": None,
        },
        "priorities": [],
        "top_risk_contributors": [],
        "change_since_last_interaction": {"source": "state_diff", "is_first_interaction": True, "details": {}},
        "house_view_alignment": [],
        "market_news": [],
    }


# --- generate_briefing, happy path ---


def test_generate_briefing_returns_all_required_keys():
    client = _FakeClient(response_text=VALID_JSON_RESPONSE)
    result = generate_briefing(_minimal_context(), client=client)
    assert "recent_development" in result
    assert "health_check" in result
    assert "outlook_and_actions" in result
    assert "read_time_estimate_seconds" in result
    assert "raw_model_response" in result


def test_generate_briefing_computes_read_time_from_word_count():
    client = _FakeClient(response_text=VALID_JSON_RESPONSE)
    result = generate_briefing(_minimal_context(), client=client)
    parsed = json.loads(VALID_JSON_RESPONSE)
    expected_words = sum(len(v.split()) for v in parsed.values())
    expected_seconds = round(expected_words / 200 * 60)
    assert result["read_time_estimate_seconds"] == expected_seconds


def test_generate_briefing_passes_prompt_to_client():
    client = _FakeClient(response_text=VALID_JSON_RESPONSE)
    generate_briefing(_minimal_context(), client=client)
    call_kwargs = client.messages.last_call_kwargs
    assert "system" in call_kwargs
    assert "Anna Meier" in call_kwargs["messages"][0]["content"]


def test_generate_briefing_uses_custom_model_string():
    client = _FakeClient(response_text=VALID_JSON_RESPONSE)
    generate_briefing(_minimal_context(), model="some-other-model", client=client)
    assert client.messages.last_call_kwargs["model"] == "some-other-model"


# --- markdown fence stripping ---


def test_generate_briefing_handles_markdown_fenced_json():
    fenced = f"```json\n{VALID_JSON_RESPONSE}\n```"
    client = _FakeClient(response_text=fenced)
    result = generate_briefing(_minimal_context(), client=client)
    assert "recent_development" in result


def test_generate_briefing_handles_plain_fenced_json_no_language_tag():
    fenced = f"```\n{VALID_JSON_RESPONSE}\n```"
    client = _FakeClient(response_text=fenced)
    result = generate_briefing(_minimal_context(), client=client)
    assert "recent_development" in result


# --- error handling ---


def test_generate_briefing_raises_on_invalid_json():
    client = _FakeClient(response_text="this is not json at all")
    try:
        generate_briefing(_minimal_context(), client=client)
        assert False, "expected BriefingGenerationError"
    except BriefingGenerationError as e:
        assert "not valid JSON" in str(e)


def test_generate_briefing_raises_on_missing_required_key():
    incomplete = json.dumps({"recent_development": "only one section"})
    client = _FakeClient(response_text=incomplete)
    try:
        generate_briefing(_minimal_context(), client=client)
        assert False, "expected BriefingGenerationError"
    except BriefingGenerationError as e:
        assert "health_check" in str(e)


def test_generate_briefing_raises_when_api_call_fails():
    client = _FakeClient(raise_error=RuntimeError("connection refused"))
    try:
        generate_briefing(_minimal_context(), client=client)
        assert False, "expected BriefingGenerationError"
    except BriefingGenerationError as e:
        assert "connection refused" in str(e)


def test_generate_briefing_raises_clear_error_when_truncated_by_max_tokens():
    # Real bug found via live testing: a genuine response got cut off
    # mid-sentence because max_tokens was too low, producing an
    # "Unterminated string" JSON error that didn't explain the real
    # cause. This must be caught explicitly and reported as truncation,
    # not surfaced as a generic JSON-parsing failure.
    truncated_json = '{"recent_development": "This got cut off mid-sen'
    client = _FakeClient(response_text=truncated_json, stop_reason="max_tokens")
    try:
        generate_briefing(_minimal_context(), client=client, max_tokens=500)
        assert False, "expected BriefingGenerationError"
    except BriefingGenerationError as e:
        assert "truncated" in str(e)
        assert "max_tokens" in str(e)
        assert "500" in str(e)


def test_generate_briefing_passes_custom_max_tokens_to_client():
    client = _FakeClient(response_text=VALID_JSON_RESPONSE)
    generate_briefing(_minimal_context(), client=client, max_tokens=8000)
    assert client.messages.last_call_kwargs["max_tokens"] == 8000


def test_generate_briefing_default_max_tokens_has_real_headroom():
    from synthesis.briefing_generator import DEFAULT_MAX_TOKENS

    # Regression guard against reintroducing the original 1024 ceiling
    # that caused a real truncated response in testing.
    assert DEFAULT_MAX_TOKENS >= 2048


# --- retry behavior ---


def test_generate_briefing_retries_after_malformed_response_and_succeeds():
    # Real bug found via live testing: one real client (CASE-002) got a
    # response missing "outlook_and_actions" entirely, with stop_reason
    # "end_turn" (not a max_tokens truncation) — genuine occasional LLM
    # unreliability in structured output. A retry is the fix; confirm it
    # actually works: first call malformed, second call valid.
    malformed = '{"recent_development": "x", "health_check": "y"},'  # missing outlook_and_actions
    client = _FakeClient(response_sequence=[(malformed, "end_turn"), (VALID_JSON_RESPONSE, "end_turn")])
    result = generate_briefing(_minimal_context(), client=client)
    assert result["recent_development"]
    assert client.messages.call_count == 2


def test_generate_briefing_raises_after_exhausting_all_attempts():
    malformed = '{"recent_development": "x", "health_check": "y"},'
    client = _FakeClient(response_text=malformed)  # every call returns the same malformed response
    try:
        generate_briefing(_minimal_context(), client=client, max_attempts=3)
        assert False, "expected BriefingGenerationError"
    except BriefingGenerationError:
        pass
    assert client.messages.call_count == 3


def test_generate_briefing_max_attempts_one_disables_retrying():
    malformed = '{"recent_development": "x", "health_check": "y"},'
    client = _FakeClient(response_text=malformed)
    try:
        generate_briefing(_minimal_context(), client=client, max_attempts=1)
        assert False, "expected BriefingGenerationError"
    except BriefingGenerationError:
        pass
    assert client.messages.call_count == 1


def test_generate_briefing_first_attempt_success_does_not_retry():
    client = _FakeClient(response_text=VALID_JSON_RESPONSE)
    generate_briefing(_minimal_context(), client=client)
    assert client.messages.call_count == 1


# --- _extract_text ---


def test_extract_text_concatenates_multiple_text_blocks():
    response = _FakeResponse([_FakeTextBlock("part1 "), _FakeTextBlock("part2")])
    assert _extract_text(response) == "part1 part2"


def test_extract_text_skips_non_text_blocks():
    response = _FakeResponse(
        [_FakeTextBlock("real text", block_type="text"), _FakeTextBlock("ignored", block_type="tool_use")]
    )
    assert _extract_text(response) == "real text"


def test_extract_text_empty_content():
    response = _FakeResponse([])
    assert _extract_text(response) == ""


# --- _parse_json_response ---


def test_parse_json_response_plain_json():
    result = _parse_json_response('{"a": 1}')
    assert result == {"a": 1}


def test_parse_json_response_strips_whitespace():
    result = _parse_json_response('  \n  {"a": 1}  \n  ')
    assert result == {"a": 1}


def test_parse_json_response_raises_briefing_error_not_json_error():
    try:
        _parse_json_response("not json")
        assert False, "expected BriefingGenerationError"
    except BriefingGenerationError:
        pass


def test_parse_json_response_handles_literal_newline_in_string_value():
    # Real bug found via live testing: a genuine model response contained
    # a literal newline character inside a JSON string value instead of
    # an escaped "\n" — invalid strict JSON, but a real LLM output
    # pattern, not a rare edge case.
    text = '{"recent_development": "First paragraph.\n\nSecond paragraph.", "health_check": "x", "outlook_and_actions": "y"}'
    result = _parse_json_response(text)
    assert "First paragraph." in result["recent_development"]
    assert "Second paragraph." in result["recent_development"]


# --- _default_client ---


def test_default_client_raises_without_api_key_or_package():
    # Whichever fails first (missing 'anthropic' package, or missing
    # ANTHROPIC_API_KEY) — both should surface as BriefingGenerationError,
    # never a raw ImportError or KeyError leaking out.
    original = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        try:
            _default_client()
            assert False, "expected BriefingGenerationError"
        except BriefingGenerationError:
            pass
    finally:
        if original is not None:
            os.environ["ANTHROPIC_API_KEY"] = original