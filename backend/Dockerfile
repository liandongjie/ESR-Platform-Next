FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_PREFER_BINARY=1

WORKDIR /app

# Rasterio, PyProj, Shapely, Pyogrio and Psycopg provide Linux wheels for
# Python 3.12. Using those wheels avoids installing the complete Debian GDAL
# development toolchain, which is large and can exhaust Docker Desktop memory.
COPY pyproject.toml ./
COPY app ./app
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --prefer-binary ".[gis]"

FROM base AS development
COPY . .
RUN python -m pip install --prefer-binary ".[dev]"
EXPOSE 5000
CMD ["python", "-m", "flask", "--app", "wsgi:app", "run", "--host=0.0.0.0", "--port=5000", "--debug"]

FROM base AS production
COPY . .
EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "120", "wsgi:app"]
