# agents/menu_agent.py
from typing import Dict, Any
from .base_agent import BaseAgent
from prompts.menu_prompt import MENU_PLANNING_PROMPT, CAKE_SELECTION_PROMPT


class MenuAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="menu_agent",
            description="Designs age-appropriate menus and cake options for parties in Turkey.",
            instruction=MENU_PLANNING_PROMPT,
            temperature=0.5,
            top_p=0.95,
            max_output_tokens=2560,
        )

    def process_request(self, inputs: Dict[str, Any]) -> str:
        task = (inputs.get("task") or inputs.get("mode") or "").lower().strip()

        # explicit switch
        if task in {"cake", "cake_selection", "cake-select"}:
            return self._generate(inputs, instruction_override=CAKE_SELECTION_PROMPT)

        # heuristic if task is not given
        cake_hint_keys = {"cake_budget_tl", "cake_portions", "cake_servings", "cake_theme", "cake_dietary"}
        if any(k in inputs for k in cake_hint_keys):
            return self._generate(inputs, instruction_override=CAKE_SELECTION_PROMPT)

        # default: full menu planning
        return self._generate(inputs, instruction_override=MENU_PLANNING_PROMPT)
