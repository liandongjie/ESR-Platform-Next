FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_PREFER_BINARY=1

WORKDIR /app

# The Python GIS wheels bundle most native dependencies, but Rasterio/GDAL
# still requires the Expat runtime shared library on slim-bookworm. Install
# only that runtime package instead of the full GDAL development toolchain.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

# Rasterio, PyProj, Shapely, Pyogrio and Psycopg provide Linux wheels for
# Python 3.12. Using those wheels avoids installing the complete Debian GDAL
# development toolchain, which is large and can exhaust Docker Desktop memory.
COPY pyproject.toml ./
COPY app ./app
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --prefer-binary ".[gis]"

# Fail the image build immediately if the slim runtime is missing a native
# shared library required by the GIS stack. This is intentionally a build-time
# smoke test so the error does not surface later during pytest or CLI execution.
RUN python -c "import geopandas, numpy, pyproj, rasterio, shapely; print('GIS runtime OK; GDAL=' + rasterio.__gdal_version__)"

FROM base AS development
COPY . .
RUN python -m pip install --prefer-binary ".[dev]"
EXPOSE 5000
CMD ["python", "-m", "flask", "--app", "wsgi:app", "run", "--host=0.0.0.0", "--port=5000", "--debug"]

FROM base AS production
COPY . .
EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "120", "wsgi:app"]
