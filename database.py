import sqlite3
import os

DB_PATH = "data/betta_farm.db"

def get_connection():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Betta Inventory Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bettas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            variety TEXT NOT NULL,
            gender TEXT CHECK(gender IN ('Male', 'Female')),
            location TEXT,
            status TEXT CHECK(status IN ('Available', 'Breeding', 'Sold', 'Deceased')),
            birth_date DATE
        )
    ''')
    
    # Spawns / Breeding Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS spawns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            spawn_code TEXT UNIQUE NOT NULL,
            male_id INTEGER,
            female_id INTEGER,
            pair_date DATE,
            eggs_hatched INTEGER DEFAULT 0,
            FOREIGN KEY (male_id) REFERENCES bettas(id),
            FOREIGN KEY (female_id) REFERENCES bettas(id)
        )
    ''')
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
