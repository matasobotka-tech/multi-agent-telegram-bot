FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot

# run as an unprivileged user; secrets come from the environment, never from the image
RUN useradd --create-home --uid 10001 bot
USER bot

CMD ["python", "-m", "bot.main"]
