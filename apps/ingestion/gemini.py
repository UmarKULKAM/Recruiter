"""Gemini Flash wrapper for JOB_PARSER.

Reads ``response.parsed``, then runs the serializer. Other modes are not called.
"""

import re

from django.conf import settings
from google import genai
from google.genai import types

from apps.ingestion.prompting import system_instruction
from apps.ingestion.schemas import JobParser
from apps.ingestion.serializers import serialize_job_parser

FLASH_MODEL = "gemini-2.5-flash"

_CLOSING_UNTRUSTED_TAG = re.compile(
    r"<\s*/\s*untrusted_(?:job_text|cv|answer)\s*>",
    re.IGNORECASE,
)


class GeminiConfigError(RuntimeError):
    """Local API key and Vertex settings are both unavailable."""


class GeminiParseError(RuntimeError):
    """The model response did not include a parsed JOB_PARSER object."""


def strip_closing_untrusted_tags(text: str) -> str:
    """Remove closing untrusted tags so source text cannot break out of the wrapper."""
    return _CLOSING_UNTRUSTED_TAG.sub("", text)


def wrap_untrusted_job_text(text: str) -> str:
    safe = strip_closing_untrusted_tags(text).strip()
    return f"<untrusted_job_text>\n{safe}\n</untrusted_job_text>"


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


def parse_posting(text: str, *, client=None) -> JobParser:
    active = client if client is not None else build_client()
    safe_text = strip_closing_untrusted_tags(text)
    response = active.models.generate_content(
        model=FLASH_MODEL,
        contents=wrap_untrusted_job_text(safe_text),
        config=types.GenerateContentConfig(
            system_instruction=system_instruction("JOB_PARSER"),
            temperature=0,
            response_mime_type="application/json",
            response_schema=JobParser,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    parsed = response.parsed
    if parsed is None:
        raise GeminiParseError("Gemini returned no parsed JOB_PARSER object.")
    if not isinstance(parsed, JobParser):
        parsed = JobParser.model_validate(parsed)
    return serialize_job_parser(parsed, source_text=safe_text)
