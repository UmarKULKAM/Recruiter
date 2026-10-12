"""Gemini wrapper for the parser, the candidate coach, and recruiter evaluation.

One client. Flash at temperature 0 for JOB_PARSER, CV_OPTIMIZER,
CANDIDATE_REPORT, and RECRUITER_EVALUATION, with thinking down.
MOCK_INTERVIEW uses Pro at about 0.2, synchronously, with thinking available.
Each call reads ``response.parsed``, then the mode serializer.
"""

import re
from typing import TypeVar

from django.conf import settings
from google import genai
from google.genai import types
from pydantic import BaseModel

from apps.ingestion.prompting import system_instruction
from apps.ingestion.schemas import JobParser
from apps.ingestion.serializers import serialize_job_parser

FLASH_MODEL = "gemini-2.5-flash"
PRO_MODEL = "gemini-2.5-pro"
PRO_TEMPERATURE = 0.2

# model, temperature, thinking budget. None leaves thinking available.
_MODE_ROUTE: dict[str, tuple[str, float, int | None]] = {
    "JOB_PARSER": (FLASH_MODEL, 0, 0),
    "CV_OPTIMIZER": (FLASH_MODEL, 0, 0),
    "CANDIDATE_REPORT": (FLASH_MODEL, 0, 0),
    "RECRUITER_EVALUATION": (FLASH_MODEL, 0, 0),
    "MOCK_INTERVIEW": (PRO_MODEL, PRO_TEMPERATURE, None),
}

_CLOSING_UNTRUSTED_TAG = re.compile(
    r"<\s*/\s*untrusted_(?:job_text|cv|answer)\s*>",
    re.IGNORECASE,
)

TModel = TypeVar("TModel", bound=BaseModel)


class GeminiConfigError(RuntimeError):
    """Local API key and Vertex settings are both unavailable."""


class GeminiParseError(RuntimeError):
    """The model response did not include a parsed object."""


def route_for(mode: str) -> tuple[str, float, int | None]:
    """Model id, temperature, and thinking budget for one mode."""
    try:
        return _MODE_ROUTE[mode]
    except KeyError as exc:
        known = ", ".join(_MODE_ROUTE)
        raise KeyError(f"No Gemini route for {mode}. Routed modes: {known}.") from exc


def strip_closing_untrusted_tags(text: str) -> str:
    """Remove closing untrusted tags so source text cannot break out of the wrapper."""
    return _CLOSING_UNTRUSTED_TAG.sub("", text)


def _wrap_untrusted(tag: str, text: str) -> str:
    safe = strip_closing_untrusted_tags(text).strip()
    return f"<{tag}>\n{safe}\n</{tag}>"


def wrap_untrusted_job_text(text: str) -> str:
    return _wrap_untrusted("untrusted_job_text", text)


def wrap_untrusted_cv(text: str) -> str:
    return _wrap_untrusted("untrusted_cv", text)


def wrap_untrusted_answer(text: str) -> str:
    return _wrap_untrusted("untrusted_answer", text)


def build_client():
    """API key locally. Vertex only when project and region are both set."""
    project = settings.VERTEX_AI_PROJECT
    location = settings.VERTEX_AI_LOCATION
    if project and location:
        return genai.Client(vertexai=True, project=project, location=location)
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise GeminiConfigError(
            "Set GEMINI_API_KEY. Vertex stays unused unless both "
            "VERTEX_AI_PROJECT and VERTEX_AI_LOCATION are set."
        )
    return genai.Client(api_key=api_key)


def generate_parsed(
    *,
    mode: str,
    contents: str,
    schema: type[TModel],
    model: str,
    temperature: float,
    client=None,
    thinking_budget: int | None = 0,
) -> TModel:
    """Synchronous ``generate_content``. Shared policy plus one mode prompt."""
    active = client if client is not None else build_client()
    config_kwargs = {
        "system_instruction": system_instruction(mode),
        "temperature": temperature,
        "response_mime_type": "application/json",
        "response_schema": schema,
    }
    if thinking_budget is not None:
        config_kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_budget=thinking_budget
        )
    response = active.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    parsed = response.parsed
    if parsed is None:
        raise GeminiParseError(f"Gemini returned no parsed {mode} object.")
    if not isinstance(parsed, schema):
        parsed = schema.model_validate(parsed)
    return parsed


def parse_posting(text: str, *, client=None) -> JobParser:
    safe_text = strip_closing_untrusted_tags(text)
    model, temperature, thinking_budget = route_for("JOB_PARSER")
    parsed = generate_parsed(
        mode="JOB_PARSER",
        contents=wrap_untrusted_job_text(safe_text),
        schema=JobParser,
        model=model,
        temperature=temperature,
        client=client,
        thinking_budget=thinking_budget,
    )
    return serialize_job_parser(parsed, source_text=safe_text)
