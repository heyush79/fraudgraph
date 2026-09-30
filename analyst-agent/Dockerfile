FROM python:3.12-slim
WORKDIR /app

# Dependencies first, read from pyproject alone, so that changing the agent's code reuses this
# layer and the next one instead of reinstalling everything and fetching the model again.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" \
      > /tmp/requirements.txt \
 && pip install --no-cache-dir -r /tmp/requirements.txt && mkdir -p /app/chroma

# Bake the embedding model into the image. Chroma's default embedding function is
# all-MiniLM-L6-v2 served through onnxruntime, and it fetches ~79 MB the first time it is
# constructed. Left to runtime that download blocks startup for minutes and repeats on every
# container recreate, because the cache lives in /root/.cache rather than the mounted volume.
RUN python -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; ONNXMiniLM_L6_V2()._download_model_if_not_exists()" \
 || python -c "import chromadb.utils.embedding_functions as ef; ef.DefaultEmbeddingFunction()(['warm the cache'])"

COPY agent ./agent
COPY evals ./evals
RUN pip install --no-cache-dir --no-deps .

EXPOSE 8000
CMD ["python", "-m", "agent.server"]
