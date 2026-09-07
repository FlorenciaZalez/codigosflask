import sqlite3
from app import app, db, Usuario, Codigo, Historial, CodigoCliente

SQLITE_PATH = 'db/codigos.db'

with app.app_context():
    with sqlite3.connect(SQLITE_PATH) as conn:
        c = conn.cursor()
        # Optimización: cargar existentes en memoria
        usuarios_existentes = set(u.nombre for u in Usuario.query.with_entities(Usuario.nombre).all())
        codigos_existentes = set((c.cuenta, c.codigo) for c in Codigo.query.with_entities(Codigo.cuenta, Codigo.codigo).all())
        codigos_cliente_existentes = set(cc.codigo_cliente for cc in CodigoCliente.query.with_entities(CodigoCliente.codigo_cliente).all())

        nuevos_usuarios = []
        nuevos_codigos = []
        nuevos_codigos_cliente = []
        nuevos_historial = []

        for row in c.execute('SELECT nombre, contraseña, rol, email, verificado FROM usuarios'):
            if row[0] not in usuarios_existentes:
                nuevos_usuarios.append(Usuario(nombre=row[0], contraseña=row[1], rol=row[2], email=row[3], verificado=bool(row[4])))
        for row in c.execute('SELECT cuenta, codigo FROM codigos'):
            if (row[0], row[1]) not in codigos_existentes:
                nuevos_codigos.append(Codigo(cuenta=row[0], codigo=row[1]))
        for row in c.execute('SELECT usuario, cuenta, codigo, fecha FROM historial'):
            nuevos_historial.append(Historial(usuario=row[0], cuenta=row[1], codigo=row[2], fecha=row[3]))
        for row in c.execute('SELECT codigo_cliente, usado FROM codigos_cliente'):
            if row[0] not in codigos_cliente_existentes:
                nuevos_codigos_cliente.append(CodigoCliente(codigo_cliente=row[0], usado=bool(row[1])))

        if nuevos_usuarios:
            db.session.bulk_save_objects(nuevos_usuarios)
        if nuevos_codigos:
            db.session.bulk_save_objects(nuevos_codigos)
        if nuevos_codigos_cliente:
            db.session.bulk_save_objects(nuevos_codigos_cliente)
        if nuevos_historial:
            db.session.bulk_save_objects(nuevos_historial)
        db.session.commit()
print('✅ Migración completada (optimizada).')
