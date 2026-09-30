# Build context is the REPO ROOT (see docker-compose.yml) so the shared proto is reachable.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# Dependencies first, read from pyproject alone: xgboost, pandas and grpcio are most of the
# image, and this way a code change reuses the layer instead of reinstalling them.
COPY ml-scorer/pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" \
      > /tmp/requirements.txt \
 && pip install --no-cache-dir -r /tmp/requirements.txt

COPY proto /proto
COPY ml-scorer/scorer ./scorer
COPY ml-scorer/training ./training
COPY ml-scorer/api ./api
COPY ml-scorer/scripts ./scripts
RUN pip install --no-cache-dir --no-deps -e . && python scripts/gen_proto.py
RUN mkdir -p /app/registry
EXPOSE 50051 8000
CMD ["python", "-m", "scorer.server"]
