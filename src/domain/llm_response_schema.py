# src/domain/llm_response_schema.py
"""
Constants for structured JSON output from LLM.

All providers (OpenAI-compatible and Gemini) are instructed to return
a wrapper object with a `response_type` discriminator field:

  {"response_type": "generation", "pim": { ... PIMFlow ... }}
  {"response_type": "clarification", "message": "What database should be used?"}

OPENAI_JSON_FORMAT is passed as `response_format` in the LLMRequest.
GeminiProvider detects it and maps it to `responseMimeType = "application/json"`.
"""

# OpenAI-compatible: forces JSON output (no markdown fences, pure JSON)
OPENAI_JSON_FORMAT: dict = {"type": "json_object"}
