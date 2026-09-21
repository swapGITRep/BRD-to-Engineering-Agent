"""
skills/json_utils.py
─────────────────────────────────────────────────────────────────────────────
Shared JSON handling for LLM responses:

  extract_json()          strips markdown fences, falls back to the first
                          {...} block
  invoke_validated_json() call the LLM, parse, validate against a pydantic
                          schema (and an optional deterministic check), and on
                          any failure retry ONCE with the exact problem fed
                          back — the single definition of that loop, shared by
                          the specialist agents (invoke_json) and by BRD
                          ingestion (classify_requirements / tag_metadata).
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Type

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


def extract_json(text: str) -> Dict[str, Any]:
    text = re.sub(r"```(?:json|python)?\s*", "", text or "").strip()
    text = re.sub(r"```\s*$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:  # noqa: BLE001
                pass
        raise ValueError(f"LLM returned invalid JSON: {e}") from e


def invoke_validated_json(
    llm: Any,
    messages: List[Any],
    *,
    schema: Optional[Type[BaseModel]] = None,
    extra_check: Optional[Callable[[Dict[str, Any]], List[str]]] = None,
    label: str = "llm",
) -> Dict[str, Any]:
    """Call `llm`, parse its JSON reply, and (optionally) validate it.

    A malformed reply — bad JSON syntax, a `schema` violation, or a problem
    reported by `extra_check` — is retried once, feeding the exact problem
    back as a follow-up turn, before a ValueError is raised for the caller
    to handle. `schema` is a pydantic model (see skills/schemas.py);
    `extra_check` returns a list of problem strings for checks a schema can't
    express (e.g. a cross-agent contract). All three share the single retry.
    Network/API errors from `llm.invoke` itself are not caught here."""

    def _parse_and_validate(text: str) -> Dict[str, Any]:
        data = extract_json(text)
        if schema is not None:
            try:
                data = schema.model_validate(data).model_dump(by_alias=True)
            except ValidationError as e:
                raise ValueError(f"response did not match the required schema: {e}") from e
        if extra_check is not None:
            problems = extra_check(data)
            if problems:
                raise ValueError("response failed a contract check: " + "; ".join(problems))
        return data

    messages = list(messages)
    resp = llm.invoke(messages)
    try:
        return _parse_and_validate(resp.content)
    except ValueError as e:
        logger.warning("invoke_validated_json(%s): %s — retrying once with the problem fed back",
                       label, e)
        messages += [
            AIMessage(content=resp.content),
            HumanMessage(content=(
                f"That response had a problem: {e}\n"
                "Return ONLY the corrected, complete, valid JSON object — no "
                "markdown fences, no commentary, nothing before or after it."
            )),
        ]
        resp = llm.invoke(messages)
        return _parse_and_validate(resp.content)
