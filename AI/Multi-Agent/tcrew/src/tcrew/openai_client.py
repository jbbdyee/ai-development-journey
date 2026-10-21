"""Real API adapter. Importing this module does not make an API call."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OpenAILLM:
    def complete(self, *, model: str, role: str, instruction: str, prompt: str) -> str:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY 환경 변수가 필요합니다")
        body = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": prompt},
            ],
        }).encode("utf-8")
        request = Request(
            "https://api.openai.com/v1/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=60) as response:
                data = json.load(response)
        except (HTTPError, URLError, TimeoutError) as exc:
            # HTTP error bodies and URLs can contain user data; never print them or the key.
            raise RuntimeError(f"LLM 호출에 실패했습니다 ({role})") from None
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"LLM 응답을 읽을 수 없습니다 ({role})") from None
