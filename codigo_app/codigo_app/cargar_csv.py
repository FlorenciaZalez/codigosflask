import csv
import sqlite3

DB_PATH = "db/codigos.db"
CSV_PATH = "db/codigos_cliente.csv"

with sqlite3.connect(DB_PATH) as conn:
    c = conn.cursor()
    with open(CSV_PATH, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            codigo = row['codigo_cliente'].strip()
            if codigo:
                c.execute("SELECT 1 FROM codigos_cliente WHERE codigo_cliente = ?", (codigo,))
                if not c.fetchone():
                    c.execute("INSERT INTO codigos_cliente (codigo_cliente, usado) VALUES (?, 0)", (codigo,))
    conn.commit()

print("✅ Códigos cargados correctamente.")