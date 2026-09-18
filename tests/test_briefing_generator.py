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
    def __init__(self, blocks):
        self.content = blocks


class _FakeMessages:
    def __init__(self, response_text=None, raise_error=None):
        self._response_text = response_text
        self._raise_error = raise_error
        self.last_call_kwargs = None

    def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        if self._raise_error is not None:
            raise self._raise_error
        return _FakeResponse([_FakeTextBlock(self._response_text)])


class _FakeClient:
    def __init__(self, response_text=None, raise_error=None):
        self.messages = _FakeMessages(response_text=response_text, raise_error=raise_error)


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
