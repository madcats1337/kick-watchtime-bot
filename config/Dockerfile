FROM python:3.11-slim

WORKDIR /app

# Install FFmpeg for clip creation
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Create clips and buffer directories
RUN mkdir -p /app/clips /app/buffer

ENV PYTHONUNBUFFERED=1

# Run combined server (Flask as main process, bot as background thread)
CMD ["python", "-u", "combined_server.py"]
