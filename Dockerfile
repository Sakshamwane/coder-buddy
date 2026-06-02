FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "groq>=0.31.0" \
    "langchain>=0.3.27" \
    "langchain-core>=0.3.72" \
    "langchain-groq>=0.3.7" \
    "langgraph>=0.6.3" \
    "pydantic>=2.11.7" \
    "python-dotenv>=1.1.1" \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.30.0"

COPY . .

RUN mkdir -p generated_project static

EXPOSE 8000

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
