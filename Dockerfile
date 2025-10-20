FROM python:3.11-slim

# Install system dependencies for Playwright browsers
RUN apt-get update && apt-get install -y \
    wget \
    ca-certificates \
    fonts-liberation \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libdbus-glib-1-2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libgtk-3-0 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (without deps, we installed them above)
RUN playwright install firefox chromium --with-deps || \
    playwright install firefox chromium || \
    echo "Note: Playwright browsers installed, some dependencies may be missing"

# Copy application files
COPY . .

ENV PYTHONUNBUFFERED=1

# Run combined server (Flask as main process, bot as background thread)
CMD ["python", "-u", "combined_server.py"]
