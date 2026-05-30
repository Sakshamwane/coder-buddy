import asyncio
import io
import json
import pathlib
import threading
import uuid
import zipfile
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

load_dotenv()

from agent.graph import agent as graph_agent
from agent.tools import _project_root_var

app = FastAPI(title="Coder Buddy")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BASE_OUTPUT = pathlib.Path("generated_project")
BASE_OUTPUT.mkdir(exist_ok=True)


class GenerateRequest(BaseModel):
    prompt: str


def _sse(event_type: str, **kwargs) -> str:
    return f"data: {json.dumps({'type': event_type, **kwargs})}\n\n"


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/generate")
async def generate(req: GenerateRequest):
    session_id = uuid.uuid4().hex[:8]
    project_root = BASE_OUTPUT / session_id
    project_root.mkdir(parents=True, exist_ok=True)

    async def stream() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def run():
            token = _project_root_var.set(project_root)
            try:
                for chunk in graph_agent.stream({"user_prompt": req.prompt}):
                    loop.call_soon_threadsafe(queue.put_nowait, chunk)
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, {"__error__": str(exc)})
            finally:
                _project_root_var.reset(token)
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=run, daemon=True).start()
        yield _sse("start", session_id=session_id)

        while True:
            chunk = await queue.get()
            if chunk is None:
                break

            if "__error__" in chunk:
                yield _sse("error", message=chunk["__error__"])
                break

            for node, data in chunk.items():
                if not isinstance(data, dict):
                    continue

                if node == "planner" and "plan" in data:
                    p = data["plan"]
                    yield _sse(
                        "planner_done",
                        name=p.name,
                        desc=p.description,
                        tech=p.techstack,
                        files=[f.path for f in p.files],
                    )

                elif node == "architect" and "task_plan" in data:
                    tp = data["task_plan"]
                    yield _sse(
                        "architect_done",
                        tasks=[t.filepath for t in tp.implementation_steps],
                    )

                elif node == "coder":
                    cs = data.get("coder_state")
                    status = data.get("status", "")
                    if cs and status != "DONE":
                        idx = cs.current_step_idx
                        steps = cs.task_plan.implementation_steps
                        total = len(steps)
                        if 0 < idx <= total:
                            yield _sse(
                                "file_done",
                                file=steps[idx - 1].filepath,
                                step=idx,
                                total=total,
                            )
                    if status == "DONE":
                        files = sorted(
                            str(f.relative_to(project_root))
                            for f in project_root.rglob("*")
                            if f.is_file()
                        )
                        yield _sse("done", session_id=session_id, files=files)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
