FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "job_automation.presentation.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
