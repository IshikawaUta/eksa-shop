# Gunakan base image resmi Python
FROM python:3.12-slim

# Instal dependensi sistem yang dibutuhkan oleh WeasyPrint
# Hapus 'sudo' dari sini
RUN apt-get update && apt-get install -y \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz-dev \
    libgirepository1.0-dev \
    libxml2-dev \
    libxslt1-dev \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Atur direktori kerja di dalam kontainer
WORKDIR /app

# Salin file requirements.txt dan instal dependensi Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Salin seluruh kode proyek Anda ke dalam kontainer
COPY . .

# Tentukan perintah untuk menjalankan aplikasi Flask Anda
CMD ["python", "api/index.py"]