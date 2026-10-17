"""
Thin LLM layer: any OpenAI-compatible provider, JSON output, Pydantic validation and retries.
"""

import json
import os
import re

from pydantic import BaseModel, ValidationError

PROVIDERS = {
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
               "key_env": "GEMINI_API_KEY", "model": "gemini-3.5-flash-lite"},
    "openai": {"base_url": None, "key_env": "OPENAI_API_KEY", "model": "gpt-4o-mini"},
}


class LLMError(Exception):
    pass


class LLM:
    def __init__(self, provider: str = "gemini", model: str | None = None, temperature: float = 0.3):
        from openai import OpenAI
        cfg = PROVIDERS[provider]
        key = os.getenv(cfg["key_env"])
        if not key:
            raise LLMError(f"{cfg['key_env']} is not set. In PowerShell: $env:{cfg['key_env']}=\"your-key\"")
        self.client = OpenAI(api_key=key, base_url=cfg["base_url"], timeout=180, max_retries=2)
        self.model = model or cfg["model"]
        self.provider = provider
        self.temperature = temperature
        self.json_mode = True

    def _call(self, messages: list[dict]) -> str:
        from openai import (APIConnectionError, APIStatusError, AuthenticationError, BadRequestError,
                            NotFoundError, RateLimitError)
        params = {"model": self.model, "messages": messages, "temperature": self.temperature}
        if self.json_mode:
            params["response_format"] = {"type": "json_object"}
        try:
            try:
                response = self.client.chat.completions.create(**params)
            except BadRequestError:
                if not self.json_mode:
                    raise
                self.json_mode = False
                params.pop("response_format")
                response = self.client.chat.completions.create(**params)
        except AuthenticationError:
            raise LLMError("authentication failed: check the API key")
        except NotFoundError:
            raise LLMError(f"model '{self.model}' not found")
        except RateLimitError as e:
            raise LLMError(f"rate limit or quota exceeded: {e}")
        except APIConnectionError:
            raise LLMError("could not connect to the LLM provider")
        except (BadRequestError, APIStatusError) as e:
            raise LLMError(f"the provider rejected the request: {e}")
        return response.choices[0].message.content or ""

    def structured(self, system: str, user: str, schema: type[BaseModel], check=None, retries: int = 2):
        """
        Ask for JSON matching `schema`, validate it with Pydantic (and the optional `check` function),
        and on failure ask again with the validation errors. Returns the validated object.
        """
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        problems = ""
        for attempt in range(1, retries + 2):
            raw = self._call(messages)
            try:
                data = parse_json(raw)
                obj = schema.model_validate(data)
                if check:
                    obj = check(obj)
                return obj
            except (ValueError, ValidationError) as e:
                problems = short_errors(e)
                print(f"  [validation failed, attempt {attempt}] {problems}")
                messages += [{"role": "assistant", "content": raw},
                             {"role": "user", "content": "Your JSON was rejected:\n" + problems +
                              "\nReturn the complete corrected JSON object only."}]
        raise LLMError(f"no valid output after {retries + 1} attempts: {problems}")


def parse_json(raw: str) -> dict:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("the response is not JSON")
        return json.loads(text[start:end + 1])


def short_errors(e: Exception) -> str:
    if isinstance(e, ValidationError):
        return "; ".join(f"{'.'.join(map(str, err['loc'])) or 'report'}: {err['msg']}" for err in e.errors()[:8])
    return str(e)
