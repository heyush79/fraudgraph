FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY generator ./generator
RUN pip install --no-cache-dir .
ENTRYPOINT ["python", "-m", "generator"]
CMD ["--tps", "50", "--fraud-rate", "0.02", "--patterns", "velocity"]
