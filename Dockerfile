FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

# Non-root user for running claude (root is blocked by --dangerously-skip-permissions)
RUN useradd -m -u 1000 -s /bin/bash claudeuser

COPY src/ ./src/
COPY web/ ./web/
COPY run_web.py .

EXPOSE 8080

# Run without --reload for stability
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8080"]
