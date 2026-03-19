FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY web/ ./web/
COPY run_web.py .

EXPOSE 8080

# Run without --reload for stability
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8080"]
