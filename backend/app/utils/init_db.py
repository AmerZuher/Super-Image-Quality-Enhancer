import psycopg2
import os

def init_database():
    # Get database connection details from environment variables
    # Use environment variables set in docker-compose.yml
    DB_HOST = os.getenv("POSTGRES_HOST", "db") # Reads from POSTGRES_HOST env var, defaults to 'db'
    DB_NAME = os.getenv("POSTGRES_DB", "image_processing") # Reads from POSTGRES_DB env var, defaults to 'image_processing'
    DB_USER = os.getenv("POSTGRES_USER", "postgres") # Reads from POSTGRES_USER env var, defaults to 'postgres'
    DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "7895123") # Reads from POSTGRES_PASSWORD env var, defaults to '7895123'

    # --- First Connection: Connect to default postgres database to create our database ---
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database="postgres", # Connect to the default 'postgres' database initially
            user=DB_USER,
            password=DB_PASSWORD
        )
        conn.autocommit = True
        cursor = conn.cursor()

        # Create database if it doesn't exist
        cursor.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s", (DB_NAME,))
        exists = cursor.fetchone()
        if not exists:
            print(f"Database '{DB_NAME}' not found. Creating...")
            # Ensure the database name is safe to use in a query
            cursor.execute(f"CREATE DATABASE {DB_NAME}")
            print(f"Database '{DB_NAME}' created successfully")
        else:
            print(f"Database '{DB_NAME}' already exists")

        cursor.close()
        conn.close()

    except psycopg2.OperationalError as e:
        print(f"Error connecting to the default 'postgres' database: {e}")
        print(f"Please ensure a PostgreSQL server is running and accessible at host '{DB_HOST}' on port 5432.")
        return # Exit if the initial connection fails

    # --- Second Connection: Connect to our specific database and create tables ---
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME, # Connect to the 'image_processing' database
            user=DB_USER,
            password=DB_PASSWORD
        )
        conn.autocommit = True
        cursor = conn.cursor()

        # Create images table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS images (
            id SERIAL PRIMARY KEY,
            original_path VARCHAR(255) NOT NULL,
            enhanced_path VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        print("Tables created successfully")

        cursor.close()
        conn.close()

    except psycopg2.OperationalError as e:
        print(f"Error connecting to the '{DB_NAME}' database: {e}")
        print(f"Please ensure the database '{DB_NAME}' exists and is accessible at host '{DB_HOST}' on port 5432.")
        return # Exit if the second connection fails


if __name__ == "__main__":
    init_database()
