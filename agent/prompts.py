def planner_prompt(user_prompt: str) -> str:
    PLANNER_PROMPT = f"""
You are the PLANNER agent. Convert the user prompt into a COMPLETE engineering project plan.

User request:
{user_prompt}
    """
    return PLANNER_PROMPT


def architect_prompt(plan: str) -> str:
    return f"""You are the ARCHITECT agent. Given this project plan, produce an ordered list of implementation tasks.

RULES:
- Create EXACTLY ONE task per file listed in the plan. No duplicates.
- Each task description must specify: what to implement, key functions/classes/variables, imports needed, and how it integrates with other files.
- Order tasks so dependencies come first (e.g. CSS before HTML that links it).

Project Plan:
{plan}
"""


def coder_prompt(filepath: str, task: str, existing: str) -> str:
    return f"""You are a senior software engineer implementing a specific file.

File: {filepath}
Task: {task}

Existing content:
{existing}

Instructions:
- Output ONLY the complete file content, nothing else.
- Do NOT include markdown code fences, explanations, or commentary.
- Write production-quality, fully functional code.
- If existing content is present, update it; otherwise write from scratch.
"""
