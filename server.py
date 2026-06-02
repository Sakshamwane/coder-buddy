import asyncio
import io
import json
import pathlib
import uuid
import zipfile

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

load_dotenv()

from agent.graph import agent as graph_agent
from agent.tools import _project_root_var

app = FastAPI(title="Coder Buddy")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BASE_OUTPUT = pathlib.Path("generated_project")
BASE_OUTPUT.mkdir(exist_ok=True)

# session_id -> {"events": [...], "done": bool}
_sessions: dict[str, dict] = {}


class GenerateRequest(BaseModel):
    prompt: str


async def _run_generation(session_id: str, project_root: pathlib.Path, prompt: str):
    sess = _sessions[session_id]

    def emit(event: dict):
        sess["events"].append(event)

    token = _project_root_var.set(project_root)
    try:
        async for chunk in graph_agent.astream(
            {"user_prompt": prompt}, {"recursion_limit": 100}
        ):
            for node, data in chunk.items():
                if not isinstance(data, dict):
                    continue

                if node == "planner" and "plan" in data:
                    p = data["plan"]
                    emit({
                        "type": "planner_done",
                        "name": p.name,
                        "desc": p.description,
                        "tech": p.techstack,
                        "files": [f.path for f in p.files],
                    })

                elif node == "architect" and "task_plan" in data:
                    tp = data["task_plan"]
                    emit({
                        "type": "architect_done",
                        "tasks": [t.filepath for t in tp.implementation_steps],
                    })

                elif node == "coder":
                    cs = data.get("coder_state")
                    status = data.get("status", "")
                    if cs and status != "DONE":
                        idx = cs.current_step_idx
                        steps = cs.task_plan.implementation_steps
                        total = len(steps)
                        if 0 < idx <= total:
                            emit({
                                "type": "file_done",
                                "file": steps[idx - 1].filepath,
                                "step": idx,
                                "total": total,
                            })
                    if status == "DONE":
                        files = sorted(
                            str(f.relative_to(project_root))
                            for f in project_root.rglob("*")
                            if f.is_file()
                        )
                        emit({"type": "done", "session_id": session_id, "files": files})

    except Exception as exc:
        emit({"type": "error", "message": str(exc)})
    finally:
        _project_root_var.reset(token)
        sess["done"] = True


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/version")
async def version():
    return {"version": "polling-v2", "build": "2026-06-03"}


@app.post("/generate")
async def generate(req: GenerateRequest):
    session_id = uuid.uuid4().hex[:8]
    project_root = BASE_OUTPUT / session_id
    project_root.mkdir(parents=True, exist_ok=True)
    _sessions[session_id] = {"events": [], "done": False}
    asyncio.create_task(_run_generation(session_id, project_root, req.prompt))
    return JSONResponse({"session_id": session_id})


@app.get("/events/{session_id}")
async def get_events(session_id: str, after: int = 0):
    if session_id not in _sessions:
        return JSONResponse({"events": [], "done": True, "total": 0})
    sess = _sessions[session_id]
    return JSONResponse({
        "events": sess["events"][after:],
        "done": sess["done"],
        "total": len(sess["events"]),
    })


@app.get("/content/{session_id}/{path:path}")
async def file_content(session_id: str, path: str):
    root = (BASE_OUTPUT / session_id).resolve()
    target = (root / path).resolve()
    if not str(target).startswith(str(root)):
        return PlainTextResponse("Forbidden", status_code=403)
    if not target.is_file():
        return PlainTextResponse("Not found", status_code=404)
    return PlainTextResponse(target.read_text(encoding="utf-8"))


@app.get("/download/{session_id}")
async def download(session_id: str):
    root = BASE_OUTPUT / session_id
    if not root.exists():
        return PlainTextResponse("Not found", status_code=404)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(root.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(root))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=project.zip"},
    )
