"""
ETL completo: descarga datos de NASA Exoplanet Archive,
normaliza tablas relacionales, crea la BD MySQL e inserta los datos.
"""

from __future__ import annotations

import os
import time
from io import StringIO

import mysql.connector
import pandas as pd
import requests
from mysql.connector import Error
from sqlalchemy import create_engine, text

# --------------------------------------------------
# Configuración
# --------------------------------------------------
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "astronomia")

NASA_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
NASA_QUERY = """
SELECT
    pl_name,
    hostname,
    pl_masse,
    pl_rade,
    pl_orbper,
    pl_orbsmax,
    st_mass,
    st_rad,
    st_teff,
    sy_snum,
    sy_pnum,
    disc_year,
    discoverymethod,
    disc_facility,
    disc_telescope,
    disc_instrument
FROM pscomppars
"""

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


def wait_for_mysql(max_attempts: int = 60, delay_seconds: float = 3.0) -> None:
    """Espera hasta que MySQL acepte conexiones."""
    print(f"Esperando MySQL en {MYSQL_HOST}:{MYSQL_PORT}...")
    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            conexion = mysql.connector.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
            )
            conexion.close()
            print(f"MySQL disponible (intento {attempt}/{max_attempts}).")
            return
        except Error as exc:
            last_error = exc
            print(f"  Intento {attempt}/{max_attempts}: aún no listo ({exc})")
            time.sleep(delay_seconds)

    raise RuntimeError(f"MySQL no respondió a tiempo: {last_error}")


def descargar_datos_nasa() -> pd.DataFrame:
    """Descarga el catálogo de exoplanetas desde NASA TAP."""
    print("Descargando datos desde NASA Exoplanet Archive...")
    respuesta = requests.get(
        NASA_URL,
        params={"query": NASA_QUERY, "format": "csv"},
        timeout=180,
    )
    respuesta.raise_for_status()
    print(f"HTTP status: {respuesta.status_code}")

    df = pd.read_csv(StringIO(respuesta.text))
    print(f"Datos descargados: {df.shape[0]} filas, {df.shape[1]} columnas")
    print(df.head())
    return df


def construir_tablas(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Normaliza el DataFrame crudo en tablas relacionales."""
    print("Construyendo tablas relacionales...")

    # ---- ESTRELLA ----
    estrellas = df[["hostname", "st_mass", "st_rad", "st_teff"]].copy()
    estrellas = estrellas.drop_duplicates(subset=["hostname"]).reset_index(drop=True)
    estrellas.insert(0, "id_estrella", range(1, len(estrellas) + 1))
    estrellas = estrellas.rename(
        columns={
            "hostname": "nombre",
            "st_mass": "masa",
            "st_rad": "radio",
            "st_teff": "temperatura",
        }
    )

    # ---- PLANETA ----
    planetas = df[
        ["pl_name", "hostname", "pl_masse", "pl_rade", "pl_orbper", "pl_orbsmax"]
    ].copy()
    planetas = planetas.rename(
        columns={
            "pl_name": "nombre",
            "pl_masse": "masa",
            "pl_rade": "radio",
            "pl_orbper": "periodo_orbital",
            "pl_orbsmax": "semieje_mayor",
        }
    )
    planetas = planetas.merge(
        estrellas[["id_estrella", "nombre"]],
        left_on="hostname",
        right_on="nombre",
        how="left",
        suffixes=("", "_estrella"),
    )
    if "nombre_estrella" in planetas.columns:
        planetas = planetas.drop(columns=["nombre_estrella"])
    planetas = planetas.drop(columns=["hostname"]).reset_index(drop=True)
    planetas.insert(0, "id_planeta", range(1, len(planetas) + 1))

    # ---- TELESCOPIO ----
    telescopios = (
        df[["disc_facility", "disc_telescope", "disc_instrument"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    telescopios = telescopios.rename(
        columns={
            "disc_facility": "instalacion",
            "disc_telescope": "nombre",
            "disc_instrument": "instrumento",
        }
    )
    telescopios.insert(0, "id_telescopio", range(1, len(telescopios) + 1))

    # ---- DESCUBRIMIENTO ----
    descubrimientos = df[
        [
            "pl_name",
            "disc_year",
            "discoverymethod",
            "disc_facility",
            "disc_telescope",
            "disc_instrument",
        ]
    ].copy()
    descubrimientos = descubrimientos.rename(
        columns={
            "pl_name": "planeta",
            "disc_year": "año",
            "discoverymethod": "metodo",
            "disc_facility": "instalacion",
            "disc_telescope": "telescopio",
            "disc_instrument": "instrumento",
        }
    )
    descubrimientos = descubrimientos.merge(
        planetas[["id_planeta", "nombre"]],
        left_on="planeta",
        right_on="nombre",
        how="left",
    )
    if "nombre" in descubrimientos.columns:
        descubrimientos = descubrimientos.drop(columns=["nombre"])

    descubrimientos = descubrimientos.merge(
        telescopios[["id_telescopio", "nombre", "instalacion", "instrumento"]],
        left_on=["telescopio", "instalacion", "instrumento"],
        right_on=["nombre", "instalacion", "instrumento"],
        how="left",
    )
    descubrimientos = descubrimientos.reset_index(drop=True)
    descubrimientos.insert(0, "id_descubrimiento", range(1, len(descubrimientos) + 1))
    descubrimientos = descubrimientos[
        ["id_descubrimiento", "id_planeta", "id_telescopio", "año", "metodo"]
    ]

    print(f"  estrellas      : {len(estrellas)}")
    print(f"  planetas       : {len(planetas)}")
    print(f"  telescopios    : {len(telescopios)}")
    print(f"  descubrimientos: {len(descubrimientos)}")

    return {
        "estrella": estrellas,
        "planeta": planetas,
        "telescopio": telescopios,
        "descubrimiento": descubrimientos,
    }


def guardar_csv(tablas: dict[str, pd.DataFrame]) -> None:
    """Guarda CSVs auxiliares (misma lógica del notebook)."""
    print("Guardando CSV auxiliares...")
    for nombre, df in tablas.items():
        ruta = os.path.join(OUTPUT_DIR, f"{nombre}.csv")
        df.to_csv(ruta, index=False)
        print(f"  -> {ruta}")


def crear_base_y_tablas() -> None:
    """Crea la base de datos astronomia y sus tablas con FKs."""
    print("Creando base de datos y tablas en MySQL...")
    config = {
        "host": MYSQL_HOST,
        "port": MYSQL_PORT,
        "user": MYSQL_USER,
        "password": MYSQL_PASSWORD,
    }

    conexion = None
    try:
        conexion = mysql.connector.connect(**config)
        cursor = conexion.cursor()

        cursor.execute(f"DROP DATABASE IF EXISTS {MYSQL_DATABASE};")
        cursor.execute(f"CREATE DATABASE {MYSQL_DATABASE};")
        cursor.execute(f"USE {MYSQL_DATABASE};")
        print(f"Base de datos '{MYSQL_DATABASE}' creada.")

        cursor.execute(
            """
            CREATE TABLE estrella (
                id_estrella INT AUTO_INCREMENT,
                nombre VARCHAR(100) NOT NULL,
                masa DECIMAL(10,4),
                radio DECIMAL(10,4),
                temperatura INT,
                PRIMARY KEY (id_estrella),
                UNIQUE (nombre)
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE telescopio (
                id_telescopio INT AUTO_INCREMENT,
                nombre VARCHAR(150),
                instalacion VARCHAR(150),
                instrumento VARCHAR(150),
                PRIMARY KEY (id_telescopio)
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE planeta (
                id_planeta INT AUTO_INCREMENT,
                id_estrella INT NOT NULL,
                nombre VARCHAR(100) NOT NULL,
                masa DECIMAL(12,5),
                radio DECIMAL(10,5),
                periodo_orbital DECIMAL(15,6),
                semieje_mayor DECIMAL(15,6),
                PRIMARY KEY (id_planeta),
                UNIQUE (nombre),
                FOREIGN KEY (id_estrella) REFERENCES estrella(id_estrella)
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE descubrimiento (
                id_descubrimiento INT AUTO_INCREMENT,
                id_planeta INT NOT NULL,
                id_telescopio INT,
                año INT,
                metodo VARCHAR(100),
                PRIMARY KEY (id_descubrimiento),
                FOREIGN KEY (id_planeta) REFERENCES planeta(id_planeta),
                FOREIGN KEY (id_telescopio) REFERENCES telescopio(id_telescopio)
            );
            """
        )

        conexion.commit()
        print("Tablas creadas respetando integridad referencial.")
    finally:
        if conexion is not None and conexion.is_connected():
            cursor.close()
            conexion.close()
            print("Conexión DDL cerrada.")


def insertar_datos(tablas: dict[str, pd.DataFrame]) -> None:
    """Inserta los DataFrames en MySQL (padres primero)."""
    print("Insertando datos en MySQL...")
    url = (
        f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}"
        f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4"
    )
    engine = create_engine(url)

    orden = ["estrella", "telescopio", "planeta", "descubrimiento"]
    with engine.begin() as conn:
        for nombre in orden:
            print(f"  Insertando {nombre}...")
            tablas[nombre].to_sql(
                name=nombre,
                con=conn,
                if_exists="append",
                index=False,
                method="multi",
                chunksize=1000,
            )

        result = conn.execute(text("SHOW TABLES;"))
        print("Tablas en la BD:", [row[0] for row in result])

    print("Base de datos cargada con éxito.")


def main() -> None:
    print("=" * 50)
    print(" ETL EXOPLANETAS -> MySQL")
    print("=" * 50)

    wait_for_mysql()
    df = descargar_datos_nasa()

    csv_crudo = os.path.join(OUTPUT_DIR, "exoplanetas_nasa.csv")
    df.to_csv(csv_crudo, index=False)
    print(f"CSV crudo guardado en: {csv_crudo}")

    tablas = construir_tablas(df)
    guardar_csv(tablas)
    crear_base_y_tablas()
    insertar_datos(tablas)

    print("=" * 50)
    print(" ETL FINALIZADO")
    print("=" * 50)


if __name__ == "__main__":
    main()
