FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
# YouTube formatlarını çözmek için JS çalıştırıcısı
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

ENV COOKIES_BROWSER=none COOKIES_FILE=/cookies/cookies.txt
EXPOSE 5050
CMD ["gunicorn", "-w", "1", "--threads", "8", "--timeout", "600", "-b", "0.0.0.0:5050", "app:app"]
