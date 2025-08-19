# agents/base_agent.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import json, os

from google.genai.types import GenerateContentConfig
from google import genai

# .env yükle
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


class BaseAgent(ABC):
    def __init__(
        self,
        *,
        name: str,
        description: str,
        instruction: str,
        model: Optional[str] = None,
        temperature: float = 0.6,
        top_p: float = 0.95,
        max_output_tokens: int = 2560,
    ) -> None:
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.instruction = instruction

        self.gen_cfg = GenerateContentConfig(
            temperature=temperature,
            top_p=top_p,
            max_output_tokens=max_output_tokens,
        )

        api_key = (
            os.environ.get("GOOGLE_API_KEY")
        )
        if not api_key:
            raise RuntimeError(
                "Missing GOOGLE_API_KEY. Put it in your .env or export it in the shell."
            )

        
        self._client = genai.Client(api_key=api_key)

    def _compose_prompt(
        self,
        payload: Dict[str, Any],
        instruction_override: Optional[str] = None
    ) -> str:
        instr = (instruction_override or self.instruction or "").strip()
        return (
            f"{instr}\n\nUSER INPUT (JSON):\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "RESPONSE REQUIREMENTS:\n"
            "- Follow the instruction precisely.\n"
            "- Use Turkish context and TL (₺) prices when relevant to Turkey.\n"
            "- Be specific and actionable.\n"
            "-Output should be plain text in English, not JSON.\n"
        )

    def _generate(
        self,
        payload: Dict[str, Any],
        instruction_override: Optional[str] = None
    ) -> str:
        content = self._compose_prompt(payload, instruction_override)
        resp = self._client.models.generate_content(
            model=self.model,
            contents=content,
            config=self.gen_cfg,
        )
        return getattr(resp, "text", str(resp))

    @abstractmethod
    def process_request(self, inputs: Dict[str, Any]) -> str:
        ...

    async def run(self, inputs: Dict[str, Any]) -> str:
        return self.process_request(inputs)
