FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir uv && uv pip install --system -e .

COPY src ./src
COPY scripts ./scripts
COPY alembic.ini ./

EXPOSE 8000 8501
CMD ["bash", "-lc", "alembic upgrade head && uvicorn proceval.api.main:app --host 0.0.0.0 --port 8000 & streamlit run src/ui/streamlit_app.py --server.port 8501 --server.address 0.0.0.0"]
