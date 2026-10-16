FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home app
RUN mkdir -p /var/lib/tuya-notifications && chown app:app /var/lib/tuya-notifications && chmod 700 /var/lib/tuya-notifications
COPY app app
COPY migrations migrations
USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
