from flask import Flask, render_template, request, redirect, session, url_for
import csv
import os
import requests  # Asegurate de que esté importado al comienzo del archivo
import smtplib
from email.message import EmailMessage
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, Integer, String, Text, DateTime, func, Boolean, inspect, text

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))
load_dotenv(os.path.join(os.path.dirname(BASE_DIR), '.env'))

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:5003")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
LOCAL_DB_URL = os.getenv('LOCAL_DATABASE_URL', f"sqlite:///{os.path.join(BASE_DIR, 'db', 'codigos.db')}")
IS_RENDER = os.getenv('RENDER', '').lower() == 'true'

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'templates'),
    static_folder=os.path.join(BASE_DIR, 'static')
)
app.secret_key = os.getenv('SECRET_KEY', 'clave_super_segura')

# Configuración de SQLAlchemy
if os.getenv('USE_LOCAL_DB', '1') == '1' and not IS_RENDER:
    DB_URL = LOCAL_DB_URL
else:
    DB_URL = os.getenv('DATABASE_URL', LOCAL_DB_URL)

if DB_URL.startswith('postgres://'):
    DB_URL = DB_URL.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DB_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


def ensure_schema_compatibility():
    with db.engine.begin() as connection:
        inspector = inspect(connection)
        if 'usuarios' in inspector.get_table_names():
            columns = {column['name'] for column in inspector.get_columns('usuarios')}
            if 'codigo_cliente' not in columns:
                connection.execute(text("ALTER TABLE usuarios ADD COLUMN codigo_cliente VARCHAR"))
            if 'activo' not in columns:
                connection.execute(text("ALTER TABLE usuarios ADD COLUMN activo BOOLEAN"))
            connection.execute(text("UPDATE usuarios SET activo = :activo WHERE activo IS NULL"), {"activo": True})

# Modelos
class Usuario(db.Model):
    __tablename__ = 'usuarios'
    id = Column(Integer, primary_key=True)
    nombre = Column(String, unique=True, nullable=False)
    contraseña = Column(String, nullable=False)
    rol = Column(String, nullable=False)
    email = Column(String, nullable=False)
    verificado = Column(Boolean, default=False)
    activo = Column(Boolean, default=True)
    codigo_cliente = Column(String, nullable=True)  # Nuevo campo para asociar código de cliente

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
    ensure_schema_compatibility()
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
        if user and not user.activo:
            mensaje = "⚠️ Tu cuenta no cumple con los requisitos para utilizar el sistema."
            return render_template('login.html', mensaje=mensaje)
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
        cuenta_lower = cuenta.lower()
        from datetime import datetime, timedelta
        hoy = datetime.now().date()
        # Si el usuario es admin, no hay restricciones
        if session.get('rol') == 'admin':
            row = Codigo.query.filter(func.lower(Codigo.cuenta) == cuenta_lower).first()
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
        usuario_actual = Usuario.query.filter_by(nombre=session['usuario']).first()
        codigo_cliente_usuario = (usuario_actual.codigo_cliente or '').strip().upper() if usuario_actual else ''
        dias_restriccion = 3
        if codigo_cliente_usuario.startswith('RV'):
            dias_restriccion = 2
        elif codigo_cliente_usuario.startswith('CF'):
            dias_restriccion = 7

        fecha_restriccion = datetime.now() - timedelta(days=dias_restriccion)
        ultima = Historial.query.filter(
            Historial.usuario == session['usuario'],
            func.lower(Historial.cuenta) == cuenta_lower
        ).order_by(Historial.fecha.desc()).first()

        if ultima and ultima.fecha > fecha_restriccion:
            dias_restantes = (ultima.fecha + timedelta(days=dias_restriccion) - datetime.now()).days + 1
            if dias_restantes < 1:
                dias_restantes = 1
            mensaje = f"⚠️ Debés esperar {dias_restantes} día(s) para volver a pedir un código de esta cuenta."
            return render_template("entregar_codigo.html", mensaje=mensaje)
        row = Codigo.query.filter(func.lower(Codigo.cuenta) == cuenta_lower).first()
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
    mensaje_gestion = ""
    historial = []
    usuarios_historial = []
    cuentas_historial = []
    mensaje_admin = ""

    # Blanquear (liberar) un código de cliente si se solicita
    if request.method == 'POST' and 'blanquear_codigo_cliente' in request.form:
        codigo_blanquear = request.form['blanquear_codigo_cliente']
        codigo_obj = CodigoCliente.query.filter_by(codigo_cliente=codigo_blanquear).first()
        if codigo_obj:
            codigo_obj.usado = False
            # Si hay un usuario con ese código, lo desvinculamos
            usuario_asociado = Usuario.query.filter_by(codigo_cliente=codigo_blanquear).first()
            if usuario_asociado:
                usuario_asociado.codigo_cliente = None
            db.session.commit()
            mensaje_csv += f"\n🔄 Código '{codigo_blanquear}' blanqueado y disponible."

    # Obtener email actual del admin
    admin_user = Usuario.query.filter_by(nombre='admin').first()
    admin_email = admin_user.email if admin_user else ''

    # Alta de códigos (insensible a mayúsculas/minúsculas)
    if 'cuenta' in request.form and 'codigo' in request.form:
        cuenta = request.form['cuenta']
        codigo = request.form['codigo']
        existe = Codigo.query.filter(
            func.lower(Codigo.cuenta) == cuenta.lower(),
            func.lower(Codigo.codigo) == codigo.lower()
        ).first()
        if not existe:
            nuevo_codigo = Codigo(cuenta=cuenta, codigo=codigo)
            db.session.add(nuevo_codigo)
            db.session.commit()
        mensaje_codigo = "✅ Código cargado correctamente"

    # Alta de usuarios (permite asignar código de cliente)
    if 'nuevo_usuario' in request.form and 'nueva_contraseña' in request.form:
        nuevo_usuario = request.form['nuevo_usuario']
        nueva_contraseña = request.form['nueva_contraseña']
        nuevo_email = request.form.get('nuevo_email', '').strip()
        rol = request.form.get('rol', 'cliente')
        codigo_cliente = request.form.get('codigo_cliente', '').strip()
        hashed_password = generate_password_hash(nueva_contraseña)
        try:
            codigo_cliente_asignado = None
            if codigo_cliente:
                # Buscar código de cliente insensible a mayúsculas/minúsculas y que no esté usado
                codigo_obj = CodigoCliente.query.filter(
                    func.lower(CodigoCliente.codigo_cliente) == codigo_cliente.lower(),
                    CodigoCliente.usado == False
                ).first()
                if not codigo_obj:
                    mensaje_usuario = f"⚠️ Código de cliente inválido o ya utilizado. Usuario no creado."
                    return render_template("admin.html", mensaje_usuario=mensaje_usuario, mensaje_codigo=mensaje_codigo, mensaje_csv=mensaje_csv, mensaje_gestion=mensaje_gestion, cuentas_codigos=[], historial=historial, usuarios_historial=usuarios_historial, cuentas_historial=cuentas_historial, mensaje_admin=mensaje_admin, admin_email=admin_email)
                codigo_obj.usado = True
                codigo_cliente_asignado = codigo_obj.codigo_cliente
            nuevo = Usuario(nombre=nuevo_usuario, contraseña=hashed_password, rol=rol, email=nuevo_email, verificado=False, codigo_cliente=codigo_cliente_asignado)
            db.session.add(nuevo)
            db.session.commit()
            # Enviar email de verificación
            from itsdangerous import URLSafeTimedSerializer
            serializer = URLSafeTimedSerializer(app.secret_key)
            token = serializer.dumps(nuevo_email)
            link = f"{BASE_URL}/verificar/{token}"
            try:
                msg = EmailMessage()
                msg.set_content(f"Hola {nuevo_usuario},\n\nPara activar tu cuenta hacé clic en el siguiente enlace:\n{link}\n\nSi no creaste esta cuenta, ignora este mensaje.")
                msg["Subject"] = "Verificación de cuenta"
                msg["From"] = EMAIL_ADDRESS
                msg["To"] = nuevo_email
                with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                    smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                    smtp.send_message(msg)
                mensaje_usuario = f"✅ Usuario '{nuevo_usuario}' creado correctamente. Se envió un correo de verificación."
            except Exception as e:
                mensaje_usuario = f"✅ Usuario '{nuevo_usuario}' creado correctamente, pero no se pudo enviar el correo de verificación: {e}"
        except Exception:
            db.session.rollback()
            mensaje_usuario = f"⚠️ El usuario '{nuevo_usuario}' ya existe"

    # Procesar archivo CSV de códigos de juego si se envía (insensible a mayúsculas/minúsculas)
    if 'archivo_csv' in request.files:
        archivo = request.files['archivo_csv']
        if archivo.filename.endswith('.csv'):
            try:
                import io
                stream = io.TextIOWrapper(archivo.stream, encoding='utf-8')
                reader = csv.DictReader(stream)
                # Cargar todos los códigos existentes en memoria para evitar consultas repetidas (en minúsculas)
                existentes = set((c.cuenta.lower(), c.codigo.lower()) for c in Codigo.query.with_entities(Codigo.cuenta, Codigo.codigo).all())
                # Cargar todos los códigos entregados en historial (en minúsculas)
                entregados = set((h.cuenta.lower(), h.codigo.lower()) for h in Historial.query.with_entities(Historial.cuenta, Historial.codigo).all())
                nuevos = []
                contador = 0
                ignoradas = 0
                obsoletos = 0
                for fila in reader:
                    cuenta = (fila.get("cuenta") or '').strip()
                    codigo = (fila.get("codigo") or '').strip()
                    if not cuenta or not codigo:
                        ignoradas += 1
                        continue
                    if (cuenta.lower(), codigo.lower()) in entregados:
                        obsoletos += 1
                        continue
                    if (cuenta.lower(), codigo.lower()) in existentes:
                        ignoradas += 1
                        continue
                    nuevos.append(Codigo(cuenta=cuenta, codigo=codigo))
                    existentes.add((cuenta.lower(), codigo.lower()))
                    contador += 1
                if nuevos:
                    db.session.bulk_save_objects(nuevos)
                    db.session.commit()
                if contador == 0:
                    mensaje_csv = f"⚠️ No se insertó ningún código válido. Revisa el formato del archivo. Filas ignoradas: {ignoradas}. Códigos obsoletos ignorados: {obsoletos}."
                else:
                    mensaje_csv = f"✅ Archivo CSV cargado correctamente. Se insertaron {contador} códigos nuevos. Filas ignoradas: {ignoradas}. Códigos obsoletos ignorados: {obsoletos}."
            except Exception as e:
                db.session.rollback()
                mensaje_csv = f"⚠️ Error al procesar el archivo: {e}"
        else:
            mensaje_csv = "⚠️ El archivo debe ser .csv"

    # Borrar todos los códigos de cliente si se solicita
    if request.method == 'POST' and request.form.get('eliminar_codigos_cliente') == '1':
        try:
            CodigoCliente.query.delete()
            db.session.commit()
            mensaje_csv += "\n🗑️ Todos los códigos de cliente fueron eliminados correctamente."
        except Exception as e:
            db.session.rollback()
            mensaje_csv += f"\n⚠️ Error al eliminar los códigos de cliente: {e}"

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
                actualizados = 0
                for fila in reader:
                    email = (fila.get('email') or '').strip().lower()
                    codigo_cliente = (fila.get('codigo_cliente') or fila.get('codigo') or '').strip()
                    if not codigo_cliente:
                        ignoradas += 1
                        continue
                    # Si el código no existe, lo agrego a la tabla CodigoCliente
                    if codigo_cliente not in existentes:
                        nuevos.append(CodigoCliente(codigo_cliente=codigo_cliente, usado=False))
                        existentes.add(codigo_cliente)
                        contador += 1
                    # Si el email existe en la tabla Usuario, actualizo su código_cliente
                    if email:
                        usuario = Usuario.query.filter(db.func.lower(Usuario.email) == email).first()
                        if usuario:
                            usuario.codigo_cliente = codigo_cliente
                            actualizados += 1
                if nuevos:
                    db.session.bulk_save_objects(nuevos)
                db.session.commit()
                mensaje_csv += f"\n✅ Códigos de cliente cargados correctamente. Se insertaron {contador} códigos nuevos. Filas ignoradas: {ignoradas}. Se actualizaron {actualizados} usuarios."
            except Exception as e:
                db.session.rollback()
                mensaje_csv += f"\n⚠️ Error al procesar los códigos de cliente: {e}"
        else:
            mensaje_csv += "\n⚠️ El archivo de códigos de cliente debe ser .csv"

    # Eliminación múltiple por cuenta: borra todos los códigos asociados a cada cuenta seleccionada
    if request.method == 'POST' and request.form.get('accion_admin') == 'eliminar_cuentas_seleccionadas':
        cuentas_raw = request.form.getlist('cuentas_seleccionadas')
        cuentas_normalizadas = []
        for cuenta in cuentas_raw:
            cuenta_limpia = (cuenta or '').strip()
            if cuenta_limpia:
                cuentas_normalizadas.append(cuenta_limpia)

        cuentas_unicas = list(dict.fromkeys(cuentas_normalizadas))

        if not cuentas_unicas:
            mensaje_gestion = "⚠️ Seleccioná al menos una cuenta para eliminar."
        else:
            try:
                eliminados_total = 0
                for cuenta in cuentas_unicas:
                    eliminados_total += Codigo.query.filter(func.lower(Codigo.cuenta) == cuenta.lower()).delete(synchronize_session=False)
                db.session.commit()
                mensaje_gestion = f"✅ Se eliminaron {eliminados_total} código(s) de {len(cuentas_unicas)} cuenta(s)."
            except Exception as e:
                db.session.rollback()
                mensaje_gestion = f"⚠️ Error al eliminar cuentas seleccionadas: {e}"

    # Listado de cuentas únicas para gestión (sin agregaciones pesadas)
    cuentas_codigos = [
        row[0] for row in db.session.query(Codigo.cuenta).distinct().order_by(Codigo.cuenta).all()
    ]
    # Ya no se mostrará la tabla de códigos de cliente en el panel admin
    # codigos_cliente = CodigoCliente.query.order_by(CodigoCliente.codigo_cliente).all()

    # Filtros para historial (insensible a mayúsculas/minúsculas)
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
            query = query.filter(Historial.usuario.ilike(f"%{usuario_filtro}%"))
        if cuenta_filtro:
            query = query.filter(Historial.cuenta.ilike(f"%{cuenta_filtro}%"))
        if fecha_inicio:
            query = query.filter(Historial.fecha >= fecha_inicio)
        if fecha_fin:
            query = query.filter(Historial.fecha <= fecha_fin)
        resultados = query.order_by(Historial.fecha.desc()).limit(100).all()
        # Convertir a lista de tuplas para el template
        historial = [(h.usuario, h.cuenta, h.codigo, h.fecha) for h in resultados]
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
                        mensaje_gestion=mensaje_gestion,
                        cuentas_codigos=cuentas_codigos,
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

@app.route('/verificar/<token>')
def verificar_cuenta(token):
    from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
    serializer = URLSafeTimedSerializer(app.secret_key)
    try:
        email = serializer.loads(token, max_age=3600*24*2)  # 2 días de validez
    except SignatureExpired:
        return "El enlace de verificación expiró. Solicita uno nuevo."
    except BadSignature:
        return "Enlace de verificación inválido."
    user = Usuario.query.filter_by(email=email).first()
    if not user:
        return "Usuario no encontrado."
    if user.verificado:
        return "La cuenta ya está verificada. Puedes iniciar sesión."
    user.verificado = True
    db.session.commit()
    return "✅ Cuenta verificada correctamente. Ya puedes iniciar sesión."
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

        # Verificar que el código exista y no haya sido usado (insensible a mayúsculas/minúsculas)
        codigo_valido = CodigoCliente.query.filter(
            func.lower(CodigoCliente.codigo_cliente) == codigo_cliente.lower(),
            CodigoCliente.usado == False
        ).first()
        if not codigo_valido:
            mensaje = "⚠️ Código de cliente inválido o ya utilizado."
        else:
            try:
                hashed_password = generate_password_hash(nueva_contraseña)
                # Asignar el código de cliente al usuario
                nuevo = Usuario(nombre=nuevo_usuario, contraseña=hashed_password, rol='cliente', email=email, verificado=False, codigo_cliente=codigo_valido.codigo_cliente)
                db.session.add(nuevo)
                # Enviar correo de verificación con token
                from itsdangerous import URLSafeTimedSerializer
                serializer = URLSafeTimedSerializer(app.secret_key)
                token = serializer.dumps(email)
                token_link = f"{BASE_URL}/verificar/{token}"
                msg = EmailMessage()
                msg.set_content(f"Hola {nuevo_usuario},\n\nPor favor verificá tu cuenta haciendo clic en el siguiente enlace:\n{token_link}\n\nSi no creaste esta cuenta, ignora este mensaje.")
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
    buscar_codigo_cliente = request.args.get('buscar_codigo_cliente', '').strip()

    # Cambiar rol de usuario
    if request.method == 'POST' and 'cambiar_rol_usuario' in request.form:
        nombre = request.form['cambiar_rol_usuario']
        nuevo_rol = request.form['nuevo_rol']
        user = Usuario.query.filter_by(nombre=nombre).first()
        if user:
            user.rol = nuevo_rol
            db.session.commit()
            mensaje = f"✅ Rol de {nombre} actualizado a {nuevo_rol}."

    # Activar/desactivar usuarios en bloque
    if request.method == 'POST' and 'accion_estado_masivo' in request.form:
        accion_estado = request.form.get('accion_estado_masivo', '').strip().lower()
        seleccion_raw = request.form.get('usuarios_seleccionados', '')
        seleccion = [nombre.strip() for nombre in seleccion_raw.split(',') if nombre.strip()]

        if not seleccion:
            mensaje = "⚠️ Debes seleccionar al menos un usuario."
        else:
            usuarios_obj = Usuario.query.filter(Usuario.nombre.in_(seleccion)).all()
            if not usuarios_obj:
                mensaje = "⚠️ No se encontraron usuarios seleccionados."
            else:
                if accion_estado == 'activar':
                    for user in usuarios_obj:
                        user.activo = True
                    mensaje = f"✅ Se activaron {len(usuarios_obj)} usuario(s)."
                elif accion_estado == 'desactivar':
                    for user in usuarios_obj:
                        user.activo = False
                    mensaje = f"✅ Se desactivaron {len(usuarios_obj)} usuario(s)."
                else:
                    for user in usuarios_obj:
                        user.activo = not bool(user.activo)
                    mensaje = f"✅ Se actualizó el estado de {len(usuarios_obj)} usuario(s)."
                db.session.commit()

    # ...eliminada función de asignar código de cliente manualmente...

    # Eliminar usuario
    if request.method == 'POST' and 'eliminar_usuario' in request.form:
        nombre = request.form['eliminar_usuario']
        user = Usuario.query.filter_by(nombre=nombre).first()
        if user:
            # Si el usuario tiene un código_cliente, lo marcamos como disponible
            if user.codigo_cliente:
                codigo_obj = CodigoCliente.query.filter_by(codigo_cliente=user.codigo_cliente).first()
                if codigo_obj:
                    codigo_obj.usado = False
            db.session.delete(user)
            db.session.commit()
            mensaje = f"🗑️ Usuario {nombre} eliminado correctamente."

    # Obtener lista de usuarios (incluyendo código de cliente), con filtro opcional por código
    query_usuarios = Usuario.query.filter(Usuario.nombre != 'admin')
    if buscar_codigo_cliente:
        query_usuarios = query_usuarios.filter(
            func.lower(func.coalesce(Usuario.codigo_cliente, '')).like(f"%{buscar_codigo_cliente.lower()}%")
        )

    # Evita errores 500 en PostgreSQL cuando existen códigos con formato no numérico.
    usuarios = query_usuarios.order_by(
        db.case((Usuario.codigo_cliente.is_(None), 1), else_=0),
        Usuario.codigo_cliente.asc(),
        Usuario.nombre.asc()
    ).all()

    # Obtener últimos accesos (última actividad registrada en historial)
    accesos = {}
    for h in db.session.query(Historial.usuario, db.func.max(Historial.fecha)).group_by(Historial.usuario).all():
        if h[0] and h[1]:
            accesos[h[0]] = h[1]

    return render_template(
        "gestionar_usuarios.html",
        usuarios=[(u.nombre, u.rol, u.email, u.verificado, u.codigo_cliente, u.activo) for u in usuarios],
        mensaje=mensaje,
        accesos=accesos,
        buscar_codigo_cliente=buscar_codigo_cliente
    )

# Ruta para verificar email
@app.route('/verificar-email/<usuario>')
def verificar_email(usuario):
    user = Usuario.query.filter(func.lower(Usuario.nombre) == usuario.lower()).first()
    if user:
        user.verificado = True
        db.session.commit()
    return render_template("verificar_email.html")

if __name__ == "__main__":
    app.run(
        host=os.getenv('FLASK_RUN_HOST', '127.0.0.1'),
        port=int(os.getenv('FLASK_RUN_PORT', '5003')),
        debug=os.getenv('FLASK_DEBUG', '1') == '1'
    )
