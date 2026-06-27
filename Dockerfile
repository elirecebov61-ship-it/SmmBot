FROM python:3.12-slim

WORKDIR /app

# PostgreSQL client libraries yükle
RUN apt-get update && apt-get install -y \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY eren_smm_postgresql.py .

CMD ["python", "eren_smm_postgresql.py"]
