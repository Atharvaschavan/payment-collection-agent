"""Tests for LLMExtractor's request construction and response parsing.

These mock the openai.OpenAI client entirely, so they run offline with no
API key -- they verify that extraction.py builds the request correctly
(system message, forced tool call) and parses the response correctly,
without depending on the model's actual extraction quality (that's what
eval/eval_harness.py is for -- see EVALUATION.md).
"""
import json
from unittest.mock import MagicMock

from payment_agent.extraction import EXTRACTION_FUNCTION_NAME, LLMExtractor
from tests.fakes import blank_extraction


def _fake_client_returning(args: dict):
    tool_call = MagicMock()
    tool_call.function.name = EXTRACTION_FUNCTION_NAME
    tool_call.function.arguments = json.dumps(args)

    message = MagicMock()
    message.tool_calls = [tool_call]

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]

    client = MagicMock()
    client.chat.completions.create.return_value = response
    return client


def test_extract_returns_the_function_call_arguments():
    client = _fake_client_returning(blank_extraction(account_id="ACC1001"))
    extractor = LLMExtractor(client=client, model="gpt-4.1-nano")

    result = extractor.extract(transcript=[], latest_user_message="ACC1001", stage_hint="await_account_id")

    assert result["account_id"] == "ACC1001"


def test_extract_forces_the_single_named_function():
    client = _fake_client_returning(blank_extraction())
    extractor = LLMExtractor(client=client, model="gpt-4.1-nano")

    extractor.extract(transcript=[], latest_user_message="hi", stage_hint="await_account_id")

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-4.1-nano"
    assert kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": EXTRACTION_FUNCTION_NAME},
    }
    assert kwargs["tools"][0]["function"]["name"] == EXTRACTION_FUNCTION_NAME
    assert kwargs["tools"][0]["function"]["strict"] is True


def test_extract_includes_a_system_message_and_the_transcript_in_order():
    client = _fake_client_returning(blank_extraction())
    extractor = LLMExtractor(client=client, model="gpt-4.1-nano")

    transcript = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello! Please share your account ID."},
    ]
    extractor.extract(transcript=transcript, latest_user_message="ACC1001", stage_hint="await_account_id")

    messages = client.chat.completions.create.call_args.kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "Hi"}
    assert messages[2] == {"role": "assistant", "content": "Hello! Please share your account ID."}
    assert messages[3]["role"] == "user"
    assert "ACC1001" in messages[3]["content"]
    assert "await_account_id" in messages[3]["content"]


def test_extract_falls_back_to_blank_if_no_tool_call_is_returned():
    message = MagicMock()
    message.tool_calls = []
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    client = MagicMock()
    client.chat.completions.create.return_value = response

    extractor = LLMExtractor(client=client, model="gpt-4.1-nano")
    result = extractor.extract(transcript=[], latest_user_message="hi", stage_hint="await_account_id")

    assert result["wants_to_stop"] is False
    assert result["account_id"] is None
