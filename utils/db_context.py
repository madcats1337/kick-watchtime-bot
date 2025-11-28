"""
Database context manager for safe connection handling
Automatically handles connection cleanup and error handling
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from urllib.parse import urlparse
from contextlib import contextmanager


@contextmanager
def db_connection(database_url, cursor_factory=None):
    """
    Context manager for database connections with automatic cleanup
    
    Usage:
        with db_connection(DATABASE_URL) as (conn, cur):
            cur.execute("SELECT * FROM users")
            results = cur.fetchall()
    
    Args:
        database_url: PostgreSQL connection string
        cursor_factory: Optional cursor factory (e.g., RealDictCursor)
    
    Yields:
        tuple: (connection, cursor) objects
    """
    conn = None
    cur = None
    
    try:
        # Parse database URL
        result = urlparse(database_url)
        
        # Create connection
        conn = psycopg2.connect(
            database=result.path[1:],
            user=result.username,
            password=result.password,
            host=result.hostname,
            port=result.port
        )
        
        # Create cursor with optional factory
        if cursor_factory:
            cur = conn.cursor(cursor_factory=cursor_factory)
        else:
            cur = conn.cursor()
        
        yield conn, cur
        
        # Commit if no exceptions
        conn.commit()
        
    except Exception as e:
        # Rollback on error
        if conn:
            conn.rollback()
        raise  # Re-raise the exception
        
    finally:
        # Always cleanup
        if cur:
            cur.close()
        if conn:
            conn.close()


@contextmanager
def db_cursor(database_url, cursor_factory=None):
    """
    Simplified context manager that yields only the cursor
    
    Usage:
        with db_cursor(DATABASE_URL) as cur:
            cur.execute("SELECT * FROM users")
            results = cur.fetchall()
    
    Args:
        database_url: PostgreSQL connection string
        cursor_factory: Optional cursor factory (e.g., RealDictCursor)
    
    Yields:
        cursor object
    """
    with db_connection(database_url, cursor_factory) as (conn, cur):
        yield cur


@contextmanager
def db_transaction(database_url, cursor_factory=None):
    """
    Context manager for explicit transactions with commit/rollback control
    Useful when you need to handle commit logic manually
    
    Usage:
        with db_transaction(DATABASE_URL) as (conn, cur):
            cur.execute("UPDATE users SET ...")
            # conn.commit() is called automatically on success
    
    Args:
        database_url: PostgreSQL connection string
        cursor_factory: Optional cursor factory (e.g., RealDictCursor)
    
    Yields:
        tuple: (connection, cursor) objects
    """
    with db_connection(database_url, cursor_factory) as (conn, cur):
        yield conn, cur
