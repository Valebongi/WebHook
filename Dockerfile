FROM python:3.12-slim

# ── ODBC Driver 17 for SQL Server ─────────────────────────────────────────────
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        curl gnupg ca-certificates apt-transport-https unixodbc unixodbc-dev gcc g++ \
 && curl -sSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
 && curl -sSL https://packages.microsoft.com/config/debian/12/prod.list \
        -o /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update \
 && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql17 \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001

CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8001}"]
