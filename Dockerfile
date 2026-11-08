FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home verification \
    && mkdir -p /app/data/artifacts && chown -R verification:verification /app/data
USER verification
EXPOSE 8000
CMD ["uvicorn", "metaforge_verification.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
