"""Small, lazy wrapper around the OpenAI-compatible LLM endpoint."""

from functools import lru_cache
import os

from config import read_secret


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL_NAME = os.getenv("LLM_MODEL", "qwen-plus")


@lru_cache(maxsize=1)
def _get_client():
    """Create the client only when an LLM request is actually made."""
    from openai import OpenAI

    api_key = read_secret("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not configured")

    try:
        timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    except ValueError as exc:
        raise RuntimeError("LLM_TIMEOUT_SECONDS must be a number") from exc

    return OpenAI(
        api_key=api_key,
        base_url=os.getenv("DASHSCOPE_BASE_URL", DEFAULT_BASE_URL),
        timeout=timeout,
        max_retries=2,
    )


def chat_completion(messages, stream=False):
    """Call the configured chat model after validating the request shape."""
    if not messages:
        raise ValueError("messages must not be empty")

    return _get_client().chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        stream=stream,
    )


def completion_content(response):
    """Extract text from a non-streaming completion with a useful error."""
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise RuntimeError("LLM returned an invalid completion") from exc

    if not content:
        raise RuntimeError("LLM returned an empty completion")
    return content
