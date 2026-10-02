#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "======================================"
echo " INSTALACIÓN AUTOMÁTICA"
echo " Proyecto Astronomía / Exoplanetas"
echo "======================================"

# --------------------------------------------------
# [1/4] Limpieza total de Docker
# --------------------------------------------------

echo ""
echo "======================================"
echo " [1/4] LIMPIANDO DOCKER"
echo "======================================"

echo "[1/5] Deteniendo todos los contenedores..."
sudo docker stop $(sudo docker ps -aq) 2>/dev/null || true

echo "[2/5] Eliminando todos los contenedores..."
sudo docker rm -f $(sudo docker ps -aq) 2>/dev/null || true

echo "[3/5] Eliminando todas las imágenes..."
sudo docker rmi -f $(sudo docker images -aq) 2>/dev/null || true

echo "[4/5] Eliminando todos los volúmenes..."
sudo docker volume rm $(sudo docker volume ls -q) 2>/dev/null || true

echo "[5/5] Limpiando redes, caché y recursos..."
sudo docker system prune -a --volumes -f

echo ""
echo "Docker limpio."
echo "Contenedores:"
sudo docker ps -a
echo ""
echo "Imágenes:"
sudo docker images
echo ""
echo "Volúmenes:"
sudo docker volume ls

# --------------------------------------------------
# [2/4] Crear contenedores con Docker Compose
# --------------------------------------------------

echo ""
echo "======================================"
echo " [2/4] CREANDO MYSQL 8.4 (Docker Compose)"
echo "======================================"

# Preferir docker compose (plugin); fallback a docker-compose
if sudo docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD="sudo docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD="sudo docker-compose"
else
  echo "ERROR: No se encontró 'docker compose' ni 'docker-compose'."
  exit 1
fi

$COMPOSE_CMD -f "$SCRIPT_DIR/docker-compose.yml" up -d

echo ""
echo "Esperando a que MySQL esté saludable..."
ATTEMPTS=0
MAX_ATTEMPTS=60
until sudo docker inspect --format='{{.State.Health.Status}}' mysql84 2>/dev/null | grep -q "healthy"; do
  ATTEMPTS=$((ATTEMPTS + 1))
  if [ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]; then
    echo "ERROR: MySQL no quedó healthy a tiempo."
    sudo docker logs mysql84 || true
    exit 1
  fi
  echo "  Esperando MySQL... ($ATTEMPTS/$MAX_ATTEMPTS)"
  sleep 3
done

echo ""
echo "Estado de contenedores:"
sudo docker ps

echo ""
echo "Red ciencia-net:"
sudo docker network inspect ciencia-net \
  --format '{{range .Containers}}{{.Name}}{{"\n"}}{{end}}' 2>/dev/null || true

echo ""
echo "MySQL listo para DBeaver / ETL / Streamlit:"
echo "  Host     : localhost"
echo "  Puerto   : 3306"
echo "  Database : astronomia"
echo "  Usuario  : root"
echo "  Password : root"
echo "  Contenedor: mysql84"
echo "  Red      : ciencia-net"

# --------------------------------------------------
# [3/4] Dependencias + ETL
# --------------------------------------------------

echo ""
echo "======================================"
echo " [3/4] ETL -> MySQL"
echo "======================================"

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "ERROR: No se encontró Python (python3/python)."
  exit 1
fi

echo "Usando intérprete: $PYTHON_BIN"
echo "Instalando dependencias desde requirements.txt..."
"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r "$SCRIPT_DIR/requirements.txt"

echo ""
echo "Ejecutando ETL (3etl_exoplanetas.py)..."
export MYSQL_HOST="${MYSQL_HOST:-localhost}"
export MYSQL_PORT="${MYSQL_PORT:-3306}"
export MYSQL_USER="${MYSQL_USER:-root}"
export MYSQL_PASSWORD="${MYSQL_PASSWORD:-root}"
export MYSQL_DATABASE="${MYSQL_DATABASE:-astronomia}"

"$PYTHON_BIN" "$SCRIPT_DIR/3etl_exoplanetas.py"

# --------------------------------------------------
# [4/4] Streamlit
# --------------------------------------------------

echo ""
echo "======================================"
echo " [4/4] INICIANDO STREAMLIT"
echo "======================================"
echo "Interfaz disponible en: http://localhost:8501"
echo "creado por: Andres David Perez"
echo "======================================"

"$PYTHON_BIN" -m streamlit run "$SCRIPT_DIR/4astronomia_app.py" --server.port 8501
