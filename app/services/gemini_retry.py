"""Retry Gemini overload responses only; the SDK retry layer is disabled by callers."""
from time import sleep

from google.genai.errors import APIError


OVERLOAD_DELAYS = (5, 15)


def request_timeout_seconds(timeout_ms, generations=1):
    per_generation = timeout_ms / 1000 * (1 + len(OVERLOAD_DELAYS)) + sum(OVERLOAD_DELAYS)
    return generations * per_generation + 20


def generate_content(generate, **kwargs):
    delays = iter(OVERLOAD_DELAYS)
    while True:
        try:
            return generate(**kwargs)
        except APIError as exc:
            delay = next(delays, None) if exc.code == 503 else None
            if delay is None:
                raise
            sleep(delay)
