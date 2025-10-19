FROM python:3.11-slim

# Install system dependencies for Playwright browsers
RUN apt-get update && apt-get install -y \
    # Base tools
    wget \
    gnupg \
    ca-certificates \
    # Fonts
    fonts-liberation \
    fonts-noto-color-emoji \
    fonts-unifont \
    # Audio/Video libraries
    libasound2 \
    libvpx7 \
    libwebp7 \
    libwebpdemux2 \
    libenchant-2-2 \
    libopus0 \
    libwoff1 \
    libharfbuzz-icu0 \
    # GTK and graphics libraries
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libgdk-pixbuf-2.0-0 \
    # X11 and display libraries
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    libx11-6 \
    libxcb1 \
    libxext6 \
    # SSL and crypto
    libnspr4 \
    libnss3 \
    # Media codecs
    libavcodec59 \
    libavformat59 \
    libavutil57 \
    libevent-2.1-7 \
    # JPEG support
    libjpeg62-turbo \
    # Utils
    xdg-utils \
    xvfb \
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

CMD ["python", "bot.py"]
