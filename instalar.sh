#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "======================================"
echo " INSTALACIÓN AUTOMÁTICA"
echo " Proyecto Astronomía / Exoplanetas"
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

# --------------------------------------------------
# [1/4] Limpieza SOLO de recursos de este proyecto
# --------------------------------------------------

echo ""
echo "======================================"
echo " [1/4] LIMPIANDO RECURSOS DEL PROYECTO"
echo "======================================"

echo "[1/5] Deteniendo y eliminando servicios de docker-compose..."
$COMPOSE_CMD -f "$SCRIPT_DIR/docker-compose.yml" down -v --remove-orphans 2>/dev/null || true

echo "[2/5] Eliminando contenedores del proyecto (si existen)..."
for CONTAINER in mysql84 jupyter; do
  if sudo docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    sudo docker rm -f "$CONTAINER" 2>/dev/null || true
    echo "  Contenedor eliminado: $CONTAINER"
  fi
done

echo "[3/5] Eliminando volumen del proyecto..."
sudo docker volume rm mysql84-data 2>/dev/null || true

echo "[4/5] Eliminando red del proyecto..."
sudo docker network rm ciencia-net 2>/dev/null || true

echo "[5/5] Eliminando imágenes usadas por este proyecto..."
sudo docker rmi -f mysql:8.4 2>/dev/null || true
sudo docker rmi -f quay.io/jupyter/scipy-notebook:latest 2>/dev/null || true

echo ""
echo "Limpieza del proyecto completada (el resto de Docker no se tocó)."

# --------------------------------------------------
# [2/4] Crear contenedores con Docker Compose
# --------------------------------------------------

echo ""
echo "======================================"
echo " [2/4] CREANDO MYSQL 8.4 (Docker Compose)"
echo "======================================"

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

SYSTEM_PYTHON=""
if command -v python3 >/dev/null 2>&1; then
  SYSTEM_PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
  SYSTEM_PYTHON="python"
else
  echo "ERROR: No se encontró Python (python3/python)."
  exit 1
fi

VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "Creando entorno virtual en .venv..."
  if ! "$SYSTEM_PYTHON" -m venv "$VENV_DIR" 2>/dev/null; then
    echo "El módulo venv no está disponible. Intentando instalar python3-venv..."
    if command -v apt-get >/dev/null 2>&1; then
      sudo apt-get update -y
      sudo apt-get install -y python3-venv python3-pip
    else
      echo "ERROR: No se pudo crear el venv. Instala python3-venv manualmente."
      exit 1
    fi
    "$SYSTEM_PYTHON" -m venv "$VENV_DIR"
  fi
fi

PYTHON_BIN="$VENV_DIR/bin/python"
echo "Usando intérprete del venv: $PYTHON_BIN"

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
