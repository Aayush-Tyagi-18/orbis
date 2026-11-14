FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY data ./data
COPY eval ./eval
ENV ORBIS_DB=/data/orbis.db
RUN useradd -m orbis && mkdir /data && chown orbis /data
USER orbis
EXPOSE 8080
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
