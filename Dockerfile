FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY prompt-blogs.md ./prompt-blogs.md

ENV DATA_DIR=/data
ENV PROMPT_PATH=/app/prompt-blogs.md
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "app.dispatcher:app", "--host", "0.0.0.0", "--port", "8080"]
