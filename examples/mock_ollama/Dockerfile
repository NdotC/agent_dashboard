FROM python:3.12-slim
RUN pip install --no-cache-dir "starlette>=0.40" "uvicorn>=0.30"
WORKDIR /app
COPY mock_ollama.py .
EXPOSE 11434
CMD ["uvicorn", "mock_ollama:app", "--host", "0.0.0.0", "--port", "11434"]
