from flask import Flask, render_template, request, redirect, session, url_for
import csv
import os
import requests  # Asegurate de que esté importado al comienzo del archivo
import smtplib
from email.message import EmailMessage
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, Integer, String, Text, DateTime, func, Boolean

load_dotenv()
BASE_URL = os.getenv("BASE_URL", "http://localhost:5003")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

app = Flask(__name__, template_folder='templates')
app.secret_key = 'clave_super_segura'

# Configuración de SQLAlchemy
DB_URL = os.getenv('DATABASE_URL')
if not DB_URL:
    raise RuntimeError("DATABASE_URL no está configurada. Debes definirla en Render con el string de conexión de PostgreSQL.")
app.config['SQLALCHEMY_DATABASE_URI'] = DB_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Modelos
class Usuario(db.Model):
    __tablename__ = 'usuarios'
    id = Column(Integer, primary_key=True)
    nombre = Column(String, unique=True, nullable=False)
    contraseña = Column(String, nullable=False)
    rol = Column(String, nullable=False)
    email = Column(String, nullable=False)
    verificado = Column(Boolean, default=False)

class Codigo(db.Model):
    __tablename__ = 'codigos'
    id = Column(Integer, primary_key=True)
    cuenta = Column(String, nullable=False)
    codigo = Column(String, nullable=False)

class Historial(db.Model):
    __tablename__ = 'historial'
    id = Column(Integer, primary_key=True)
    usuario = Column(String, nullable=False)
    cuenta = Column(String, nullable=False)
    codigo = Column(String, nullable=False)
    fecha = Column(DateTime, default=func.now())

class CodigoCliente(db.Model):
    __tablename__ = 'codigos_cliente'
    id = Column(Integer, primary_key=True)
    codigo_cliente = Column(String, unique=True, nullable=False)
    usado = Column(Boolean, default=False)

# Crear tablas y usuario admin por defecto usando SQLAlchemy y contexto Flask
with app.app_context():
    db.create_all()
    if not Usuario.query.filter_by(nombre='admin').first():
        hashed = generate_password_hash('1234')
        admin = Usuario(nombre='admin', contraseña=hashed, rol='admin', email='admin@mail.com', verificado=True)
        db.session.add(admin)
        db.session.commit()

@app.route('/')
def home_redirect():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        nombre_o_email = request.form['usuario']
        contraseña = request.form['contraseña']
        # Buscar usuario por nombre o email, insensible a mayúsculas/minúsculas
        nombre_o_email_lower = nombre_o_email.lower()
        user = Usuario.query.filter(
            (func.lower(Usuario.nombre) == nombre_o_email_lower) |
            (func.lower(Usuario.email) == nombre_o_email_lower)
        ).first()
        if user and not user.verificado:
            return "⚠️ Tu cuenta aún no fue verificada. Por favor revisá tu correo para activarla."
        if user and check_password_hash(user.contraseña, contraseña):
            session['usuario'] = user.nombre
            session['rol'] = user.rol
            return redirect(url_for('home'))
        else:
            mensaje = "❌ Usuario o contraseña incorrectos"
            return render_template('login.html', mensaje=mensaje)
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/home')
def home():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    return render_template('home.html', usuario=session['usuario'], rol=session['rol'])

@app.route('/codigo', methods=['GET', 'POST'])
def entregar_codigo():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    mensaje = ""
    if request.method == 'POST':
        cuenta = request.form['cuenta']
        from datetime import datetime, timedelta
        hoy = datetime.now().date()
        # Si el usuario es admin, no hay restricciones
        if session.get('rol') == 'admin':
            row = Codigo.query.filter_by(cuenta=cuenta).first()
            if row:
                codigo_id = row.id
                codigo = row.codigo
                db.session.delete(row)
                nuevo_historial = Historial(usuario=session['usuario'], cuenta=cuenta, codigo=codigo)
                db.session.add(nuevo_historial)
                db.session.commit()
                mensaje = f"✅ Tu código es: {codigo}"
            else:
                mensaje = "⚠️ No hay códigos disponibles para esta cuenta."
            return render_template("entregar_codigo.html", mensaje=mensaje)
        # Restricciones para usuarios comunes
        codigos_hoy = Historial.query.filter_by(usuario=session['usuario']).filter(db.func.date(Historial.fecha) == hoy).count()
        if codigos_hoy >= 10:
            mensaje = "⚠️ Límite diario alcanzado: no podés pedir más de 10 códigos hoy."
            return render_template("entregar_codigo.html", mensaje=mensaje)
        tres_dias_atras = datetime.now() - timedelta(days=3)
        ultima = Historial.query.filter_by(usuario=session['usuario'], cuenta=cuenta).order_by(Historial.fecha.desc()).first()
        if ultima and ultima.fecha > tres_dias_atras:
            dias_restantes = (ultima.fecha + timedelta(days=3) - datetime.now()).days + 1
            mensaje = f"⚠️ Debés esperar {dias_restantes} día(s) para volver a pedir un código de esta cuenta."
            return render_template("entregar_codigo.html", mensaje=mensaje)
        row = Codigo.query.filter_by(cuenta=cuenta).first()
        if row:
            codigo_id = row.id
            codigo = row.codigo
            db.session.delete(row)
            nuevo_historial = Historial(usuario=session['usuario'], cuenta=cuenta, codigo=codigo)
            db.session.add(nuevo_historial)
            db.session.commit()
            mensaje = f"✅ Tu código es: {codigo}"
        else:
            mensaje = "⚠️ No hay códigos disponibles para esta cuenta."
    return render_template("entregar_codigo.html", mensaje=mensaje)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    mensaje_codigo = ""
    mensaje_usuario = ""
    mensaje_csv = ""
    historial = []
    usuarios_historial = []
    cuentas_historial = []
    mensaje_admin = ""

    # Obtener email actual del admin
    admin_user = Usuario.query.filter_by(nombre='admin').first()
    admin_email = admin_user.email if admin_user else ''

    # Eliminar todos los códigos de juegos si se solicita
    if request.method == 'POST' and request.form.get('eliminar_todos_codigos') == '1':
        try:
            Codigo.query.delete()
            db.session.commit()
            mensaje_csv = "🗑️ Todos los códigos de juegos fueron eliminados correctamente."
        except Exception as e:
            db.session.rollback()
            mensaje_csv = f"⚠️ Error al eliminar los códigos: {e}"

    # Alta de códigos
    if 'cuenta' in request.form and 'codigo' in request.form:
        cuenta = request.form['cuenta']
        codigo = request.form['codigo']
        existe = Codigo.query.filter_by(cuenta=cuenta, codigo=codigo).first()
        if not existe:
            nuevo_codigo = Codigo(cuenta=cuenta, codigo=codigo)
            db.session.add(nuevo_codigo)
            db.session.commit()
        mensaje_codigo = "✅ Código cargado correctamente"

    # Alta de usuarios
    if 'nuevo_usuario' in request.form and 'nueva_contraseña' in request.form:
        nuevo_usuario = request.form['nuevo_usuario']
        nueva_contraseña = request.form['nueva_contraseña']
        rol = request.form.get('rol', 'cliente')
        hashed_password = generate_password_hash(nueva_contraseña)
        try:
            nuevo = Usuario(nombre=nuevo_usuario, contraseña=hashed_password, rol=rol, email='', verificado=True)
            db.session.add(nuevo)
            db.session.commit()
            mensaje_usuario = f"✅ Usuario '{nuevo_usuario}' creado correctamente"
        except Exception:
            db.session.rollback()
            mensaje_usuario = f"⚠️ El usuario '{nuevo_usuario}' ya existe"

    # Procesar archivo CSV de códigos de juego si se envía
    if 'archivo_csv' in request.files:
        archivo = request.files['archivo_csv']
        if archivo.filename.endswith('.csv'):
            try:
                import io
                stream = io.TextIOWrapper(archivo.stream, encoding='utf-8')
                reader = csv.DictReader(stream)
                # Cargar todos los códigos existentes en memoria para evitar consultas repetidas
                existentes = set((c.cuenta, c.codigo) for c in Codigo.query.with_entities(Codigo.cuenta, Codigo.codigo).all())
                nuevos = []
                contador = 0
                ignoradas = 0
                for fila in reader:
                    cuenta = (fila.get("cuenta") or '').strip()
                    codigo = (fila.get("codigo") or '').strip()
                    if not cuenta or not codigo:
                        ignoradas += 1
                        continue
                    if (cuenta, codigo) in existentes:
                        ignoradas += 1
                        continue
                    nuevos.append(Codigo(cuenta=cuenta, codigo=codigo))
                    existentes.add((cuenta, codigo))
                    contador += 1
                if nuevos:
                    db.session.bulk_save_objects(nuevos)
                    db.session.commit()
                if contador == 0:
                    mensaje_csv = f"⚠️ No se insertó ningún código válido. Revisa el formato del archivo. Filas ignoradas: {ignoradas}."
                else:
                    mensaje_csv = f"✅ Archivo CSV cargado correctamente. Se insertaron {contador} códigos nuevos. Filas ignoradas: {ignoradas}."
            except Exception as e:
                db.session.rollback()
                mensaje_csv = f"⚠️ Error al procesar el archivo: {e}"
        else:
            mensaje_csv = "⚠️ El archivo debe ser .csv"

    # Procesar archivo CSV de códigos de cliente si se envía
    if 'archivo_codigos_cliente' in request.files:
        archivo = request.files['archivo_codigos_cliente']
        if archivo.filename.endswith('.csv'):
            try:
                contenido = archivo.read().decode('utf-8').splitlines()
                reader = csv.DictReader(contenido)
                existentes = set(c.codigo_cliente for c in CodigoCliente.query.with_entities(CodigoCliente.codigo_cliente).all())
                nuevos = []
                contador = 0
                ignoradas = 0
                for fila in reader:
                    codigo_cliente = (fila.get('codigo_cliente') or fila.get('codigo') or '').strip()
                    if not codigo_cliente or codigo_cliente in existentes:
                        ignoradas += 1
                        continue
                    nuevos.append(CodigoCliente(codigo_cliente=codigo_cliente, usado=False))
                    existentes.add(codigo_cliente)
                    contador += 1
                if nuevos:
                    db.session.bulk_save_objects(nuevos)
                    db.session.commit()
                if contador == 0:
                    mensaje_csv += "\n⚠️ No se insertó ningún código de cliente válido. Revisa el formato del archivo. Filas ignoradas: {}.".format(ignoradas)
                else:
                    mensaje_csv += "\n✅ Códigos de cliente cargados correctamente. Se insertaron {} códigos nuevos. Filas ignoradas: {}.".format(contador, ignoradas)
            except Exception as e:
                db.session.rollback()
                mensaje_csv += f"\n⚠️ Error al procesar los códigos de cliente: {e}"
        else:
            mensaje_csv += "\n⚠️ El archivo de códigos de cliente debe ser .csv"

    # Mostrar códigos
    codigos = Codigo.query.order_by(Codigo.cuenta).all()

    # Filtros para historial
    usuario_filtro = request.args.get('usuario_filtro', '').strip()
    cuenta_filtro = request.args.get('cuenta_filtro', '').strip()
    fecha_inicio = request.args.get('fecha_inicio', '').strip()
    fecha_fin = request.args.get('fecha_fin', '').strip()

    # Obtener todos los usuarios únicos y cuentas únicas del historial SIEMPRE
    usuarios_historial = [u[0] for u in db.session.query(Historial.usuario).distinct().order_by(Historial.usuario).all()]
    cuentas_historial = [c[0] for c in db.session.query(Historial.cuenta).distinct().order_by(Historial.cuenta).all()]

    # Solo buscar si hay algún filtro aplicado
    if usuario_filtro or cuenta_filtro or fecha_inicio or fecha_fin:
        query = Historial.query
        if usuario_filtro:
            query = query.filter_by(usuario=usuario_filtro)
        if cuenta_filtro:
            query = query.filter_by(cuenta=cuenta_filtro)
        if fecha_inicio:
            query = query.filter(Historial.fecha >= fecha_inicio)
        if fecha_fin:
            query = query.filter(Historial.fecha <= fecha_fin)
        historial = query.order_by(Historial.fecha.desc()).limit(100).all()
    else:
        historial = []

    # 🔴 BORRAR TODOS LOS CÓDIGOS (USO TEMPORAL)
    if request.args.get('borrar_codigos') == '1':
        Codigo.query.delete()
        db.session.commit()
        mensaje_codigo = "🗑️ Todos los códigos fueron eliminados"

    # --- CAMBIO DE CREDENCIALES DE ADMIN ---
    if request.method == 'POST' and 'cambiar_admin' in request.form:
        nuevo_email = request.form.get('nuevo_email', '').strip()
        nueva_contraseña = request.form.get('nueva_contraseña', '').strip()
        confirmar_contraseña = request.form.get('confirmar_contraseña', '').strip()
        if nueva_contraseña and nueva_contraseña != confirmar_contraseña:
            mensaje_admin = "⚠️ Las contraseñas no coinciden."
        else:
            if admin_user:
                if nuevo_email:
                    admin_user.email = nuevo_email
                    mensaje_admin += "✅ Email actualizado. "
                if nueva_contraseña:
                    admin_user.contraseña = generate_password_hash(nueva_contraseña)
                    mensaje_admin += "✅ Contraseña actualizada. "
                db.session.commit()
            if not nuevo_email and not nueva_contraseña:
                mensaje_admin = "⚠️ Debes ingresar un nuevo email o contraseña."

    return render_template("admin.html",
                        mensaje_codigo=mensaje_codigo,
                        mensaje_usuario=mensaje_usuario,
                        mensaje_csv=mensaje_csv,
                        historial=historial,
                        usuarios_historial=usuarios_historial,
                        cuentas_historial=cuentas_historial,
                        mensaje_admin=mensaje_admin,
                        admin_email=admin_email)

@app.route('/recuperar-clave', methods=['GET', 'POST'])
def recuperar_clave():
    mensaje = ""
    if request.method == 'POST':
        email = request.form['email']
        user = Usuario.query.filter_by(email=email).first()
        if user:
            nombre = user.nombre
            reset_link = f"{BASE_URL}/resetear-clave/{nombre}"
            try:
                msg = EmailMessage()
                msg.set_content(f"Hola {nombre},\n\nPara cambiar tu contraseña hacé clic en el siguiente enlace:\n{reset_link}")
                msg["Subject"] = "Recuperación de contraseña"
                msg["From"] = EMAIL_ADDRESS
                msg["To"] = email
                with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                    smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                    smtp.send_message(msg)
                mensaje = "📩 Se envió un correo con las instrucciones para recuperar la contraseña."
            except Exception as e:
                mensaje = f"⚠️ No se pudo enviar el correo: {e}"
        else:
            mensaje = "⚠️ No se encontró ninguna cuenta con ese correo."
    return render_template("recuperar_clave.html", mensaje=mensaje)

@app.route('/register', methods=['GET', 'POST'])
def register():
    mensaje = ""
    if request.method == 'POST':
        nuevo_usuario = request.form['usuario']
        nueva_contraseña = request.form['contraseña']
        confirmar_contraseña = request.form['confirmar_contraseña']
        codigo_cliente = request.form.get('codigo_cliente', '').strip()
        email = request.form.get('email', '').strip()

        if nueva_contraseña != confirmar_contraseña:
            mensaje = "⚠️ Las contraseñas no coinciden."
            return render_template("register.html", mensaje=mensaje)

        if not email:
            mensaje = "⚠️ Debés ingresar un correo electrónico válido."
            return render_template("register.html", mensaje=mensaje)

        # Verificar que el código exista y no haya sido usado
        codigo_valido = CodigoCliente.query.filter_by(codigo_cliente=codigo_cliente, usado=False).first()
        if not codigo_valido:
            mensaje = "⚠️ Código de cliente inválido o ya utilizado."
        else:
            try:
                hashed_password = generate_password_hash(nueva_contraseña)
                nuevo = Usuario(nombre=nuevo_usuario, contraseña=hashed_password, rol='cliente', email=email, verificado=False)
                db.session.add(nuevo)
                # Enviar correo de verificación
                token_link = f"{BASE_URL}/verificar-email/{nuevo_usuario}"
                msg = EmailMessage()
                msg.set_content(f"Hola {nuevo_usuario},\n\nPor favor verificá tu cuenta haciendo clic en el siguiente enlace:\n{token_link}")
                msg["Subject"] = "Verificá tu cuenta"
                msg["From"] = EMAIL_ADDRESS
                msg["To"] = email
                try:
                    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                        smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                        smtp.send_message(msg)
                except Exception as e:
                    print(f"Error enviando correo de verificación: {e}")
                codigo_valido.usado = True
                db.session.commit()
                mensaje = "✅ Cuenta creada con éxito. Iniciá sesión."
            except Exception:
                db.session.rollback()
                mensaje = "⚠️ Ese usuario ya existe."
        return render_template("register.html", mensaje=mensaje)
    return render_template("register.html")


# Ruta para resetear la clave de un usuario
@app.route('/resetear-clave/<usuario>', methods=['GET', 'POST'])
def resetear_clave(usuario):
    mensaje = ""
    if request.method == 'POST':
        nueva_contraseña = request.form['nueva_contraseña']
        confirmar_contraseña = request.form['confirmar_contraseña']
        if nueva_contraseña != confirmar_contraseña:
            mensaje = "⚠️ Las contraseñas no coinciden."
        else:
            user = Usuario.query.filter_by(nombre=usuario).first()
            if user:
                user.contraseña = generate_password_hash(nueva_contraseña)
                db.session.commit()
                mensaje = "✅ Contraseña actualizada correctamente. Podés iniciar sesión."
    return render_template("resetear_clave.html", mensaje=mensaje, usuario=usuario)



# Nueva ruta para gestionar usuarios (admin)
@app.route('/gestionar-usuarios', methods=['GET', 'POST'])
def gestionar_usuarios():
    if 'usuario' not in session or session.get('rol') != 'admin':
        return redirect(url_for('login'))

    mensaje = ""

    # Cambiar rol de usuario
    if request.method == 'POST' and 'cambiar_rol_usuario' in request.form:
        nombre = request.form['cambiar_rol_usuario']
        nuevo_rol = request.form['nuevo_rol']
        user = Usuario.query.filter_by(nombre=nombre).first()
        if user:
            user.rol = nuevo_rol
            db.session.commit()
            mensaje = f"✅ Rol de {nombre} actualizado a {nuevo_rol}."

    # Eliminar usuario
    if request.method == 'POST' and 'eliminar_usuario' in request.form:
        nombre = request.form['eliminar_usuario']
        user = Usuario.query.filter_by(nombre=nombre).first()
        if user:
            db.session.delete(user)
            db.session.commit()
            mensaje = f"🗑️ Usuario {nombre} eliminado correctamente."

    # Obtener lista de usuarios
    usuarios = Usuario.query.filter(Usuario.nombre != 'admin').order_by(Usuario.nombre).all()

    # Obtener últimos accesos (última actividad registrada en historial)
    accesos = {}
    for h in db.session.query(Historial.usuario, db.func.max(Historial.fecha)).group_by(Historial.usuario).all():
        if h[0] and h[1]:
            accesos[h[0]] = h[1]

    return render_template("gestionar_usuarios.html", usuarios=[(u.nombre, u.rol, u.email, u.verificado) for u in usuarios], mensaje=mensaje, accesos=accesos)

# Ruta para verificar email
@app.route('/verificar-email/<usuario>')
def verificar_email(usuario):
    user = Usuario.query.filter_by(nombre=usuario).first()
    if user:
        user.verificado = True
        db.session.commit()
    return render_template("verificar_email.html")

if __name__ == "__main__":
    app.run(debug=True)

