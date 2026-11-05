FROM python:3.12-slim
RUN pip install --no-cache-dir "ollama>=0.4"
WORKDIR /app
COPY simple_agent.py .
ENV PYTHONUNBUFFERED=1
CMD ["python", "simple_agent.py"]
