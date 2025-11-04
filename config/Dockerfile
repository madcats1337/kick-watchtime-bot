FROM python:3.11-slim

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

ENV PYTHONUNBUFFERED=1

# Run combined server (Flask as main process, bot as background thread)
CMD ["python", "-u", "combined_server.py"]
