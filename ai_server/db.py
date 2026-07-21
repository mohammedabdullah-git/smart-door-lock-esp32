import json
import mysql.connector
from mysql.connector import Error


DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "smart_door_ai",
    "charset": "utf8mb4",
    "use_unicode": True
}


def get_connection():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn

    except Error as e:
        raise RuntimeError(f"Cannot connect to MySQL: {e}")


def create_tables_if_not_exists():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id VARCHAR(50) NOT NULL UNIQUE,
            name VARCHAR(100) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS face_embeddings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id VARCHAR(50) NOT NULL,
            embedding_json LONGTEXT NOT NULL,
            image_path VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
                ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS access_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id VARCHAR(50),
            name VARCHAR(100),
            status VARCHAR(50) NOT NULL,
            access_granted BOOLEAN NOT NULL,
            score FLOAT,
            image_path VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    cursor.close()
    conn.close()


def user_exists(user_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT user_id FROM users WHERE user_id = %s",
        (user_id,)
    )

    row = cursor.fetchone()

    cursor.close()
    conn.close()

    return row is not None


def create_user(user_id, name):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO users (user_id, name)
            VALUES (%s, %s)
            """,
            (user_id, name)
        )

        conn.commit()

    except Error as e:
        conn.rollback()
        raise RuntimeError(f"Cannot create user: {e}")

    finally:
        cursor.close()
        conn.close()


def save_embedding(user_id, embedding, image_path=None):
    conn = get_connection()
    cursor = conn.cursor()

    embedding_json = json.dumps(embedding)

    try:
        cursor.execute(
            """
            INSERT INTO face_embeddings (user_id, embedding_json, image_path)
            VALUES (%s, %s, %s)
            """,
            (user_id, embedding_json, image_path)
        )

        conn.commit()

    except Error as e:
        conn.rollback()
        raise RuntimeError(f"Cannot save embedding: {e}")

    finally:
        cursor.close()
        conn.close()


def delete_user(user_id):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "DELETE FROM users WHERE user_id = %s",
            (user_id,)
        )

        if cursor.rowcount == 0:
            raise RuntimeError(f"User not found: {user_id}")

        conn.commit()

    except Error as e:
        conn.rollback()
        raise RuntimeError(f"Cannot delete user: {e}")

    finally:
        cursor.close()
        conn.close()


def get_all_users():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT user_id, name, created_at
        FROM users
        ORDER BY created_at DESC
        """
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    result = []

    for row in rows:
        result.append({
            "user_id": row["user_id"],
            "name": row["name"],
            "created_at": str(row["created_at"])
        })

    return result


def get_all_embeddings():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT 
            u.user_id,
            u.name,
            fe.embedding_json,
            fe.image_path,
            fe.created_at
        FROM face_embeddings fe
        JOIN users u ON fe.user_id = u.user_id
        ORDER BY fe.created_at DESC
        """
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    result = []

    for row in rows:
        result.append({
            "user_id": row["user_id"],
            "name": row["name"],
            "embedding": json.loads(row["embedding_json"]),
            "image_path": row["image_path"],
            "created_at": str(row["created_at"])
        })

    return result


def save_access_log(
    user_id,
    name,
    status,
    access_granted,
    score,
    image_path=None
):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO access_logs (
                user_id,
                name,
                status,
                access_granted,
                score,
                image_path
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                name,
                status,
                access_granted,
                score,
                image_path
            )
        )

        conn.commit()

    except Error as e:
        conn.rollback()
        raise RuntimeError(f"Cannot save access log: {e}")

    finally:
        cursor.close()
        conn.close()


def get_access_logs(limit=50):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT 
            id,
            user_id,
            name,
            status,
            access_granted,
            score,
            image_path,
            created_at
        FROM access_logs
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (limit,)
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    result = []

    for row in rows:
        result.append({
            "id": row["id"],
            "user_id": row["user_id"],
            "name": row["name"],
            "status": row["status"],
            "access_granted": bool(row["access_granted"]),
            "score": row["score"],
            "image_path": row["image_path"],
            "created_at": str(row["created_at"])
        })

    return result

def update_user(user_id, new_name):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            UPDATE users
            SET name = %s
            WHERE user_id = %s
            """,
            (new_name, user_id)
        )

        if cursor.rowcount == 0:
            raise RuntimeError(f"User not found: {user_id}")

        conn.commit()

    except Error as e:
        conn.rollback()
        raise RuntimeError(f"Cannot update user: {e}")

    finally:
        cursor.close()
        conn.close()