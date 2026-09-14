FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY agent ./agent
COPY evals ./evals
RUN pip install --no-cache-dir . && mkdir -p /app/chroma

# Bake the embedding model into the image. Chroma's default embedding function is
# all-MiniLM-L6-v2 served through onnxruntime, and it fetches ~79 MB the first time it is
# constructed. Left to runtime that download blocks startup for minutes and repeats on every
# container recreate, because the cache lives in /root/.cache rather than the mounted volume.
RUN python -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; ONNXMiniLM_L6_V2()._download_model_if_not_exists()" \
 || python -c "import chromadb.utils.embedding_functions as ef; ef.DefaultEmbeddingFunction()(['warm the cache'])"

EXPOSE 8000
CMD ["python", "-m", "agent.server"]
