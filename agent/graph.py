import re

from dotenv import load_dotenv
from langchain_core.globals import set_verbose, set_debug
from langchain_groq.chat_models import ChatGroq
from langgraph.constants import END
from langgraph.graph import StateGraph

from agent.prompts import *
from agent.states import *
from agent.tools import write_file, read_file

_ = load_dotenv()

set_debug(False)
set_verbose(False)

llm = ChatGroq(model="llama-3.3-70b-versatile")


def _strip_code_block(text: str) -> str:
    """Remove markdown code fences if the LLM wrapped its output in them."""
    text = text.strip()
    match = re.match(r"^```[^\n]*\n(.*?)```$", text, re.DOTALL)
    if match:
        return match.group(1)
    return text


def planner_agent(state: dict) -> dict:
    user_prompt = state["user_prompt"]
    resp = llm.with_structured_output(Plan).invoke(planner_prompt(user_prompt))
    if resp is None:
        raise ValueError("Planner returned no response.")
    return {"plan": resp}


def architect_agent(state: dict) -> dict:
    plan: Plan = state["plan"]
    resp = llm.with_structured_output(TaskPlan).invoke(
        architect_prompt(plan=plan.model_dump_json())
    )
    if resp is None:
        raise ValueError("Architect returned no response.")
    resp.plan = plan
    # One task per file — keep only the first occurrence of each filepath
    seen: set[str] = set()
    resp.implementation_steps = [
        s for s in resp.implementation_steps
        if not (s.filepath in seen or seen.add(s.filepath))
    ]
    return {"task_plan": resp}


def coder_agent(state: dict) -> dict:
    coder_state: CoderState = state.get("coder_state")
    if coder_state is None:
        coder_state = CoderState(task_plan=state["task_plan"], current_step_idx=0)

    steps = coder_state.task_plan.implementation_steps
    if coder_state.current_step_idx >= len(steps):
        return {"coder_state": coder_state, "status": "DONE"}

    current_task = steps[coder_state.current_step_idx]
    existing_content = read_file.invoke({"path": current_task.filepath})

    prompt = coder_prompt(
        filepath=current_task.filepath,
        task=current_task.task_description,
        existing=existing_content or "(empty)",
    )

    response = llm.invoke([{"role": "user", "content": prompt}])
    content = _strip_code_block(response.content)
    write_file.invoke({"path": current_task.filepath, "content": content})

    coder_state.current_step_idx += 1
    return {"coder_state": coder_state}


graph = StateGraph(dict)
graph.add_node("planner", planner_agent)
graph.add_node("architect", architect_agent)
graph.add_node("coder", coder_agent)
graph.add_edge("planner", "architect")
graph.add_edge("architect", "coder")
graph.add_conditional_edges(
    "coder",
    lambda s: "END" if s.get("status") == "DONE" else "coder",
    {"END": END, "coder": "coder"},
)
graph.set_entry_point("planner")
agent = graph.compile()
