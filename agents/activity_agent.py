# agents/activity_agent.py
from typing import Dict, Any
from .base_agent import BaseAgent
from prompts.activity_prompt import ACTIVITY_PLANNING_PROMPT


class ActivityAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="activity_agent",
            description="Creates age-appropriate activity timelines and backups.",
            instruction=ACTIVITY_PLANNING_PROMPT,
            temperature=0.5,
            top_p=0.95,
            max_output_tokens=2560,
        )

    def process_request(self, inputs: Dict[str, Any]) -> str:
        return self._generate(inputs, instruction_override=ACTIVITY_PLANNING_PROMPT)
