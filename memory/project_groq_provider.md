---
name: project-groq-provider
description: Groq added as a free LLM provider option for development and testing to avoid API costs
metadata:
  type: project
---

Groq free inference added as a third LLM provider alongside Anthropic and OpenAI.

**Why:** User wants to test the pipeline for free during development before paying for Claude/OpenAI.

**How to apply:** When helping with LLM-related code, the pattern now has three branches: `claude*` → anthropic, `LLM_PROVIDER=groq` → groq (OpenAI SDK + base_url), else → openai. Recommend `llama-3.3-70b-versatile` as the default Groq model. For production use, Claude is still the primary option.

Implementation: `LLM_PROVIDER` env var (auto | groq | openai) in `.env`. Stages 2 and 3 both read this. Groq uses the OpenAI Python SDK with `base_url="https://api.groq.com/openai/v1"`.
