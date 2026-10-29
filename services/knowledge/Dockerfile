FROM python:3.12-slim
WORKDIR /app
COPY --from=ai-source /requirements /app/requirements
RUN pip install --no-cache-dir --require-hashes -r /app/requirements/runtime.lock -r /app/requirements/rag.lock
COPY --from=ai-source /src /app/ai-src
ENV PYTHONPATH=/app/ai-src PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt /app/service-requirements.txt
RUN pip install --no-cache-dir -r /app/service-requirements.txt
COPY *.py /app/
RUN useradd --system app
USER app
EXPOSE 8010
CMD ["python", "-m", "uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "1"]
