# Build context is the REPO ROOT (see docker-compose.yml) so the shared proto is reachable.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY proto /proto
COPY ml-scorer/pyproject.toml ./
COPY ml-scorer/scorer ./scorer
COPY ml-scorer/training ./training
COPY ml-scorer/api ./api
COPY ml-scorer/scripts ./scripts
RUN pip install --no-cache-dir -e . && python scripts/gen_proto.py
RUN mkdir -p /app/registry
EXPOSE 50051 8000
CMD ["python", "-m", "scorer.server"]
