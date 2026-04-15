import psycopg2
from psycopg2.extras import RealDictCursor
import os


def get_db_connection():
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "db"),
        database=os.getenv("POSTGRES_DB", "image_processing"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "7895123")
    )
    conn.autocommit = True
    return conn
