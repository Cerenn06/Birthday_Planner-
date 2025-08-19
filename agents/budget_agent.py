# agents/budget_agent.py
from typing import Dict, Any
from .base_agent import BaseAgent
from prompts.budget_prompt import BUDGET_CALCULATION_PROMPT


class BudgetAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="budget_agent",
            description="Breaks down TL costs, per-guest pricing, and optimizations for Turkey.",
            instruction=BUDGET_CALCULATION_PROMPT,
            temperature=0.4,
            top_p=0.95,
            max_output_tokens=2560,
        )

    def process_request(self, inputs: Dict[str, Any]) -> str:
        return self._generate(inputs, instruction_override=BUDGET_CALCULATION_PROMPT)
