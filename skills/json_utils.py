"""
skills/json_utils.py
─────────────────────────────────────────────────────────────────────────────
Shared JSON extraction for LLM responses (strips markdown fences, falls back to
the first {...} block).
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict


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
