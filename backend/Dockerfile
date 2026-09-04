FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app --home /home/app app

COPY pyproject.toml README.md ./
COPY src ./src
COPY app ./app

RUN python -m pip install .

RUN chown -R app:app /app /home/app
USER app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "interview_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
