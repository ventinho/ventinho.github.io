FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Lisbon \
    CE_HOST=0.0.0.0 \
    CE_PORT=8050 \
    CE_DB=/app/data/criptoestrategia.db

WORKDIR /app
COPY *.py ./
COPY static ./static

# Corre como root dentro do contentor para conseguir escrever sempre na pasta ./data montada do PC
# (o Docker cria-a como root; com um utilizador sem privilégios a base de dados não abria).
RUN mkdir -p /app/data

EXPOSE 8050
VOLUME ["/app/data"]

HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8050/api/status', timeout=5); sys.exit(0)"

CMD ["python", "main.py", "--no-browser"]
