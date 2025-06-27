from flask import Flask, render_template, request, redirect, session, url_for
import csv
from werkzeug.utils import secure_filename
import sqlite3
import os
import requests  # Asegurate de que esté importado al comienzo del archivo
import smtplib
from email.message import EmailMessage
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
load_dotenv()
BASE_URL = os.getenv("BASE_URL", "http://localhost:5003")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

app = Flask(__name__)
app.secret_key = 'clave_super_segura'
DB_PATH = "db/codigos.db"

# Crear la base si no existe
os.makedirs("db", exist_ok=True)
with sqlite3.connect(DB_PATH) as conn:
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE,
            contraseña TEXT,
            rol TEXT,
            email TEXT,
            verificado INTEGER DEFAULT 0
        )
    """)
    # Si se desea filtrar por estado, agregar la columna 'estado' a la tabla codigos:
    # c.execute("ALTER TABLE codigos ADD COLUMN estado TEXT DEFAULT 'disponible'")
    # Por defecto, la tabla no tiene la columna 'estado'. Si se requiere, agregarla.
    c.execute("""
        CREATE TABLE IF NOT EXISTS codigos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cuenta TEXT,
            codigo TEXT
            -- estado TEXT DEFAULT 'disponible'  -- Descomentar si se quiere usar filtros por estado
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS historial (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT,
            cuenta TEXT,
            codigo TEXT,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS codigos_cliente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo_cliente TEXT UNIQUE,
            usado INTEGER DEFAULT 0
        )
    """)
    from werkzeug.security import generate_password_hash

    hashed = generate_password_hash('1234')
    c.execute("SELECT * FROM usuarios WHERE nombre = 'admin'")
    if not c.fetchone():
        c.execute("INSERT INTO usuarios (nombre, contraseña, rol, email, verificado) VALUES (?, ?, ?, ?, ?)", ('admin', hashed, 'admin', 'admin@mail.com', 1))

@app.route('/')
def index():
    if 'usuario' in session:
        return redirect(url_for('home'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        nombre = request.form['usuario']
        contraseña = request.form['contraseña']
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM usuarios WHERE nombre = ?", (nombre,))
            user = c.fetchone()
            if user and len(user) > 5 and user[5] == 0:
                return "⚠️ Tu cuenta aún no fue verificada. Por favor revisá tu correo para activarla."
            if user and check_password_hash(user[2], contraseña):
                session['usuario'] = user[1]
                session['rol'] = user[3]
                return redirect(url_for('home'))
            else:
                return "❌ Usuario o contraseña incorrectos"
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
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            from datetime import datetime, timedelta

            # Restricción 1: máximo 10 códigos por día
            hoy = datetime.now().strftime('%Y-%m-%d')
            c.execute("""
                SELECT COUNT(*) FROM historial
                WHERE usuario = ? AND DATE(fecha) = ?
            """, (session['usuario'], hoy))
            codigos_hoy = c.fetchone()[0]
            if codigos_hoy >= 10:
                mensaje = "⚠️ Límite diario alcanzado: no podés pedir más de 10 códigos hoy."
                return render_template("entregar_codigo.html", mensaje=mensaje)

            # Restricción 2: esperar 5 días para volver a pedir de la misma cuenta
            cinco_dias_atras = datetime.now() - timedelta(days=5)
            c.execute("""
                SELECT MAX(fecha) FROM historial
                WHERE usuario = ? AND cuenta = ?
            """, (session['usuario'], cuenta))
            if (ultima_entrega := c.fetchone()[0]):
                ultima_fecha = datetime.strptime(ultima_entrega, '%Y-%m-%d %H:%M:%S')
                if ultima_fecha > cinco_dias_atras:
                    dias_restantes = (ultima_fecha + timedelta(days=5) - datetime.now()).days + 1
                    mensaje = f"⚠️ Debés esperar {dias_restantes} día(s) para volver a pedir un código de esta cuenta."
                    return render_template("entregar_codigo.html", mensaje=mensaje)

            # Buscar primer código disponible
            # Si se desea filtrar por estado, asegurarse de que la columna 'estado' exista en la tabla 'codigos'.
            # c.execute("SELECT id, codigo FROM codigos WHERE cuenta = ? AND estado = 'disponible' LIMIT 1", (cuenta,))
            c.execute("SELECT id, codigo FROM codigos WHERE cuenta = ? LIMIT 1", (cuenta,))
            row = c.fetchone()
            if row:
                codigo_id, codigo = row
                # Eliminar el código entregado
                c.execute("DELETE FROM codigos WHERE id = ?", (codigo_id,))
                # Guardar en historial
                c.execute("""
                    INSERT INTO historial (usuario, cuenta, codigo)
                    VALUES (?, ?, ?)
                """, (session['usuario'], cuenta, codigo))
                mensaje = f"✅ Tu código es: {codigo}"
            else:
                mensaje = "⚠️ No hay códigos disponibles para esta cuenta."
                # Enviar WhatsApp si no hay códigos
                whatsapp_message = f"⚠️ La cuenta {cuenta} se quedó sin códigos disponibles."
                url = f"https://api.callmebot.com/whatsapp.php?phone=+549XXXXXXXXXX&text={whatsapp_message}&apikey=YOUR_API_KEY"
                try:
                    requests.get(url)
                except:
                    print("No se pudo enviar el WhatsApp de aviso.")

    return render_template("entregar_codigo.html", mensaje=mensaje)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if 'usuario' not in session or session.get('rol') != 'admin':
        return redirect(url_for('login'))

    mensaje_codigo = ""
    mensaje_usuario = ""
    mensaje_csv = ""

    # --- IMPORTAR CÓDIGOS DESDE GOOGLE SHEETS ---
    # Para importar desde Google Sheets, descomentar el siguiente bloque:
    # url_csv = "https://docs.google.com/spreadsheets/d/1bHY-StAJI7-QOi7dS3HANMh-Zt5dWuUiMmrWZAEdcOs/export?format=csv"
    # Reemplazado por el nuevo enlace solicitado:
    # url_csv = "https://docs.google.com/spreadsheets/d/1NYyGnr0L7zxHjEgHosZSnaJK8TerzcVRJLJwK8Eo9Ic/export?format=csv"

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()

        # Alta de códigos
        if 'cuenta' in request.form and 'codigo' in request.form:
            cuenta = request.form['cuenta']
            codigo = request.form['codigo']
            # Verificar si ya existe ese código para esa cuenta antes de insertar
            c.execute("SELECT 1 FROM codigos WHERE cuenta = ? AND codigo = ?", (cuenta, codigo))
            if not c.fetchone():
                c.execute("INSERT INTO codigos (cuenta, codigo) VALUES (?, ?)", (cuenta, codigo))
            mensaje_codigo = "✅ Código cargado correctamente"

        # Alta de usuarios
        if 'nuevo_usuario' in request.form and 'nueva_contraseña' in request.form:
            nuevo_usuario = request.form['nuevo_usuario']
            nueva_contraseña = request.form['nueva_contraseña']
            rol = request.form.get('rol', 'cliente')
            try:
                c.execute("INSERT INTO usuarios (nombre, contraseña, rol, email, verificado) VALUES (?, ?, ?, '', 1)",
                        (nuevo_usuario, nueva_contraseña, rol))
                mensaje_usuario = f"✅ Usuario '{nuevo_usuario}' creado correctamente"
            except sqlite3.IntegrityError:
                mensaje_usuario = f"⚠️ El usuario '{nuevo_usuario}' ya existe"


        # Procesar archivo CSV de códigos de juego si se envía
        print("🟡 Verificando si hay archivo_csv en request.files:", request.files)
        if 'archivo_csv' in request.files:
            archivo = request.files['archivo_csv']
            if archivo.filename.endswith('.csv'):
                print("🟢 Archivo CSV recibido:", archivo.filename)
                try:
                    import io
                    stream = io.TextIOWrapper(archivo.stream, encoding='utf-8')
                    reader = csv.DictReader(stream)
                    print("CSV campos:", reader.fieldnames)
                    contador = 0
                    for fila in reader:
                        print("Fila leída:", fila)
                        cuenta = fila.get("cuenta", "").strip()
                        codigo = fila.get("codigo", "").strip()
                        if cuenta and codigo:
                            c.execute("SELECT 1 FROM codigos WHERE cuenta = ? AND codigo = ?", (cuenta, codigo))
                            if not c.fetchone():
                                c.execute("INSERT INTO codigos (cuenta, codigo) VALUES (?, ?)", (cuenta, codigo))
                                contador += 1
                    mensaje_csv = f"✅ Archivo CSV cargado correctamente. Se insertaron {contador} códigos nuevos."
                except Exception as e:
                    mensaje_csv = f"⚠️ Error al procesar el archivo: {e}"
            else:
                mensaje_csv = "⚠️ El archivo debe ser .csv"

        # Importar códigos desde Google Sheets
        if 'importar_desde_google_sheets' in request.form:
            try:
                import requests
                import io
                url_csv = "https://docs.google.com/spreadsheets/d/1NYyGnr0L7zxHjEgHosZSnaJK8TerzcVRJLJwK8Eo9Ic/export?format=csv"
                response = requests.get(url_csv)
                response.encoding = 'utf-8'
                stream = io.StringIO(response.text)
                reader = csv.DictReader(stream)
                print("🧪 Encabezados detectados:", reader.fieldnames)
                contador = 0
                for fila in reader:
                    # Buscar claves compatibles sin depender del nombre exacto
                    for key in fila.keys():
                        print("🔍 Clave encontrada:", key)  # DEBUG

                    cuenta = next((fila[k] for k in fila if k.strip().lower() == "cuenta"), "").strip()
                    codigo = next((fila[k] for k in fila if k.strip().lower() == "codigo"), "").strip()
                    if cuenta and codigo:
                        c.execute("SELECT 1 FROM codigos WHERE cuenta = ? AND codigo = ?", (cuenta, codigo))
                        if not c.fetchone():
                            c.execute("INSERT INTO codigos (cuenta, codigo) VALUES (?, ?)", (cuenta, codigo))
                            contador += 1
                mensaje_csv += f"\n✅ Se importaron {contador} códigos desde Google Sheets."
            except Exception as e:
                mensaje_csv += f"\n⚠️ Error al importar desde Google Sheets: {e}"

        # Procesar archivo CSV de códigos de cliente si se envía
        if 'archivo_codigos_cliente' in request.files:
            archivo = request.files['archivo_codigos_cliente']
            if archivo.filename.endswith('.csv'):
                try:
                    contenido = archivo.read().decode('utf-8').splitlines()
                    reader = csv.DictReader(contenido)
                    for fila in reader:
                        codigo_cliente = fila.get('codigo_cliente') or fila.get('codigo') or ''
                        codigo_cliente = codigo_cliente.strip()
                        if codigo_cliente:
                            c.execute("SELECT 1 FROM codigos_cliente WHERE codigo_cliente = ?", (codigo_cliente,))
                            if not c.fetchone():
                                c.execute("INSERT INTO codigos_cliente (codigo_cliente, usado) VALUES (?, 0)", (codigo_cliente,))
                    mensaje_csv += "\n✅ Códigos de cliente cargados correctamente"
                except Exception as e:
                    mensaje_csv += f"\n⚠️ Error al procesar los códigos de cliente: {e}"
            else:
                mensaje_csv += "\n⚠️ El archivo de códigos de cliente debe ser .csv"

        # Mostrar códigos
        c.execute("SELECT cuenta, codigo FROM codigos ORDER BY cuenta")
        codigos = c.fetchall()

        # Filtros para historial
        usuario_filtro = request.args.get('usuario_filtro', '').strip()
        cuenta_filtro = request.args.get('cuenta_filtro', '').strip()
        query = "SELECT usuario, cuenta, codigo, fecha FROM historial"
        params = []

        if usuario_filtro:
            query += " WHERE usuario = ?"
            params.append(usuario_filtro)

        if cuenta_filtro:
            if params:
                query += " AND cuenta = ?"
            else:
                query += " WHERE cuenta = ?"
            params.append(cuenta_filtro)

        query += " ORDER BY fecha DESC LIMIT 100"
        c.execute(query, tuple(params))
        historial = c.fetchall()

        # Obtener todos los usuarios únicos y cuentas únicas del historial
        c.execute("SELECT DISTINCT usuario FROM historial ORDER BY usuario")
        usuarios_historial = [fila[0] for fila in c.fetchall()]
        c.execute("SELECT DISTINCT cuenta FROM historial ORDER BY cuenta")
        cuentas_historial = [fila[0] for fila in c.fetchall()]

        # 🔴 BORRAR TODOS LOS CÓDIGOS (USO TEMPORAL)
        if request.args.get('borrar_codigos') == '1':
            c.execute("DELETE FROM codigos")
            conn.commit()
            mensaje_codigo = "🗑️ Todos los códigos fueron eliminados"

    return render_template("admin.html",
                        mensaje_codigo=mensaje_codigo,
                        mensaje_usuario=mensaje_usuario,
                        mensaje_csv=mensaje_csv,
                        historial=historial,
                        usuarios_historial=usuarios_historial,
                        cuentas_historial=cuentas_historial)

@app.route('/recuperar-clave', methods=['GET', 'POST'])
def recuperar_clave():
    mensaje = ""
    if request.method == 'POST':
        email = request.form['email']
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT nombre FROM usuarios WHERE email = ?", (email,))
            resultado = c.fetchone()
            if resultado:
                nombre = resultado[0]
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

        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()

            # Asegurarse de que la columna 'verificado' exista
            c.execute("PRAGMA table_info(usuarios)")
            columns = [col[1] for col in c.fetchall()]
            if 'verificado' not in columns:
                c.execute("ALTER TABLE usuarios ADD COLUMN verificado INTEGER DEFAULT 0")

            # Verificar que el código exista y no haya sido usado
            c.execute("SELECT * FROM codigos_cliente WHERE codigo_cliente = ? AND usado = 0", (codigo_cliente,))
            codigo_valido = c.fetchone()

            if not codigo_valido:
                mensaje = "⚠️ Código de cliente inválido o ya utilizado."
            else:
                try:
                    hashed_password = generate_password_hash(nueva_contraseña)
                    c.execute("INSERT INTO usuarios (nombre, contraseña, rol, email, verificado) VALUES (?, ?, ?, ?, 0)",
                            (nuevo_usuario, hashed_password, 'cliente', email))
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
                    c.execute("UPDATE codigos_cliente SET usado = 1 WHERE codigo_cliente = ?", (codigo_cliente,))
                    mensaje = "✅ Cuenta creada con éxito. Iniciá sesión."
                except sqlite3.IntegrityError:
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
            with sqlite3.connect(DB_PATH) as conn:
                c = conn.cursor()
                hashed_password = generate_password_hash(nueva_contraseña)
                c.execute("UPDATE usuarios SET contraseña = ? WHERE nombre = ?", (hashed_password, usuario))
                mensaje = "✅ Contraseña actualizada correctamente. Podés iniciar sesión."

    return render_template("resetear_clave.html", mensaje=mensaje, usuario=usuario)



# Nueva ruta para gestionar usuarios (admin)
@app.route('/gestionar-usuarios', methods=['GET', 'POST'])
def gestionar_usuarios():
    if 'usuario' not in session or session.get('rol') != 'admin':
        return redirect(url_for('login'))

    mensaje = ""

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()

        # Cambiar rol de usuario
        if request.method == 'POST' and 'cambiar_rol_usuario' in request.form:
            nombre = request.form['cambiar_rol_usuario']
            nuevo_rol = request.form['nuevo_rol']
            c.execute("UPDATE usuarios SET rol = ? WHERE nombre = ?", (nuevo_rol, nombre))
            mensaje = f"✅ Rol de {nombre} actualizado a {nuevo_rol}."

        # Eliminar usuario
        if request.method == 'POST' and 'eliminar_usuario' in request.form:
            nombre = request.form['eliminar_usuario']
            c.execute("DELETE FROM usuarios WHERE nombre = ?", (nombre,))
            mensaje = f"🗑️ Usuario {nombre} eliminado correctamente."

        # Obtener lista de usuarios
        c.execute("SELECT nombre, rol, email, verificado FROM usuarios WHERE nombre != 'admin' ORDER BY nombre")
        usuarios = c.fetchall()

        # Obtener últimos accesos (última actividad registrada en historial)
        c.execute("""
            SELECT usuario, MAX(fecha) as ultimo_acceso
            FROM historial
            GROUP BY usuario
        """)
        resultados = c.fetchall()
        accesos = {}
        for fila in resultados:
            if fila and len(fila) == 2 and fila[0] and fila[1]:
                accesos[fila[0]] = fila[1]

    return render_template("gestionar_usuarios.html", usuarios=usuarios, mensaje=mensaje, accesos=accesos)

# Ruta para verificar email
@app.route('/verificar-email/<usuario>')
def verificar_email(usuario):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE usuarios SET verificado = 1 WHERE nombre = ?", (usuario,))
    return render_template("verificar_email.html")

if __name__ == '__main__':
    app.run(debug=True, port=5003)