FROM python:3.12-slim
WORKDIR /app
COPY sdk/python /sdk
RUN pip install --no-cache-dir /sdk "ollama>=0.4" "httpx>=0.27"
COPY examples/multi_agent_demo/newsroom.py .
ENV PYTHONUNBUFFERED=1
CMD ["python", "newsroom.py"]
