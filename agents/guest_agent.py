# agents/guest_agent.py
from typing import Dict, Any
from .base_agent import BaseAgent
from prompts.guest_prompt import GUEST_MANAGEMENT_PROMPT


class GuestAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="guest_agent",
            description="Handles invites, RSVPs, dietary collection, transportation, and thank-you notes.",
            instruction=GUEST_MANAGEMENT_PROMPT,
            temperature=0.4,
            top_p=0.95,
            max_output_tokens=2560,
        )

    def process_request(self, inputs: Dict[str, Any]) -> str:
        return self._generate(inputs, instruction_override=GUEST_MANAGEMENT_PROMPT)
