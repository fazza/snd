FROM python:3.11-slim

# Install Chromium + matching ChromeDriver from apt (always version-matched, no runtime downloads)
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Tell the Python scripts where to find the chromium binary
ENV CHROME_BIN=/usr/bin/chromium

# Set working directory
WORKDIR /app

# Copy requirements and install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app files
COPY . .

# Create data directory
RUN mkdir -p /data

ENV PORT=5001

EXPOSE $PORT

CMD gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 300 golf_server:app
