FROM python:3.12-slim

WORKDIR /app
COPY backend/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY backend/ ./

ENV APP_ENV=production
EXPOSE 5200
CMD ["gunicorn", "-c", "gunicorn.conf.py", "main:app"]
