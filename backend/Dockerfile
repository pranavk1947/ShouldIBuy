FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Install uv (fast resolver/installer).
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy project metadata first for better layer caching.
COPY pyproject.toml README.md ./
COPY src ./src

# Install the package (non-editable) into the system env.
RUN uv pip install --system --no-cache .

EXPOSE 8000

CMD ["uvicorn", "shouldibuy.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
