import sqlite3
import os
from app import db, Usuario, Codigo, Historial, CodigoCliente

# Ruta a tu base SQLite local
SQLITE_PATH = 'db/codigos.db'

with sqlite3.connect(SQLITE_PATH) as conn:
    c = conn.cursor()
    # Usuarios
    for row in c.execute('SELECT nombre, contraseña, rol, email, verificado FROM usuarios'):
        if not Usuario.query.filter_by(nombre=row[0]).first():
            db.session.add(Usuario(nombre=row[0], contraseña=row[1], rol=row[2], email=row[3], verificado=bool(row[4])))
    # Códigos
    for row in c.execute('SELECT cuenta, codigo FROM codigos'):
        if not Codigo.query.filter_by(cuenta=row[0], codigo=row[1]).first():
            db.session.add(Codigo(cuenta=row[0], codigo=row[1]))
    # Historial
    for row in c.execute('SELECT usuario, cuenta, codigo, fecha FROM historial'):
        db.session.add(Historial(usuario=row[0], cuenta=row[1], codigo=row[2], fecha=row[3]))
    # Códigos cliente
    for row in c.execute('SELECT codigo_cliente, usado FROM codigos_cliente'):
        if not CodigoCliente.query.filter_by(codigo_cliente=row[0]).first():
            db.session.add(CodigoCliente(codigo_cliente=row[0], usado=bool(row[1])))
    db.session.commit()
print('✅ Migración completada.')
