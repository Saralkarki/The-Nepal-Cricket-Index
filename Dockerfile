FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SECURE_DEPLOYMENT=true

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY manage.py ./
COPY config/ config/
COPY cricket_nepal/ cricket_nepal/
RUN mkdir -p data

RUN DJANGO_SECRET_KEY=build-only-placeholder DJANGO_ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput \
    && useradd --system --no-create-home --uid 10001 dashboard \
    && chown dashboard:dashboard /app

USER dashboard
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "config.wsgi:application"]
