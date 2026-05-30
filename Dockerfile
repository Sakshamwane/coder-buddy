FROM python:3.11-slim

WORKDIR /app

RUN pip install uv --no-cache-dir

COPY pyproject.toml uv.lock ./
RUN uv venv && uv pip install -r pyproject.toml

COPY . .

RUN mkdir -p generated_project static

EXPOSE 8000

CMD ["sh", "-c", ".venv/bin/uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
