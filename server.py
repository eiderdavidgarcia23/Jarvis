import os
import json
import re
import requests
import subprocess
import tempfile
import hmac
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import base64
import io
from pypdf import PdfReader
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, send_from_directory, Response, session, redirect
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
import hashlib, base64 as b64_mod
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__, static_folder='public', static_url_path='')

# --- CORS restringido ---
# Antes: CORS(app) permitía CUALQUIER origen. Ahora solo el/los origenes que definas
# en CORS_ORIGINS (separados por coma) en tu .env. Si no defines nada, no se permite
# ningun origen externo (mismo origen sigue funcionando siempre).
_cors_origins = [o.strip() for o in os.environ.get('CORS_ORIGINS', '').split(',') if o.strip()]
if _cors_origins:
    CORS(app, origins=_cors_origins, supports_credentials=True)

# --- SECRET_KEY obligatorio ---
# Antes tenia un valor por defecto hardcodeado ('clave-temporal-cambiar-en-env').
# Como el codigo es publico en GitHub, ese valor por defecto permitia forjar
# cookies de sesion validas. Ahora el servidor se niega a arrancar sin una clave
# real definida en el entorno.
app.secret_key = os.environ.get('SECRET_KEY')
if not app.secret_key or app.secret_key == 'clave-temporal-cambiar-en-env':
    raise RuntimeError(
        'Falta SECRET_KEY (o sigue con el valor por defecto inseguro). '
        'Genera una con: python3 -c "import secrets; print(secrets.token_hex(32))" '
        'y ponla en tu .env como SECRET_KEY=...'
    )

app.permanent_session_lifetime = timedelta(days=30)

# --- Configuracion de cookies de sesion ---
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('COOKIE_SECURE', '1') == '1'

JARVIS_PASSWORD = os.environ.get('JARVIS_PASSWORD', '')

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY')
GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta/interactions'
MODELO_TEXTO = 'gemini-3.7-flash'
MODELO_VISION = 'gemini-3.7-flash'

MEMORIA_DIR = os.path.join(os.path.dirname(__file__), 'memorias')
RECORDATORIOS_DIR = os.path.join(os.path.dirname(__file__), 'recordatorios')
PREFERENCIAS_DIR = os.path.join(os.path.dirname(__file__), 'preferencias')
os.makedirs(MEMORIA_DIR, exist_ok=True)
os.makedirs(RECORDATORIOS_DIR, exist_ok=True)
os.makedirs(PREFERENCIAS_DIR, exist_ok=True)

MODO_AVANZADO = os.environ.get('MODO_AVANZADO', '') == '1'

USUARIOS_DIR = os.path.join(os.path.dirname(__file__), 'usuarios')
os.makedirs(USUARIOS_DIR, exist_ok=True)

# --- Rate limiting simple en memoria (sin dependencias nuevas) ---
# Para algo mas robusto en produccion real usarias flask-limiter + redis, pero
# para un proyecto personal en Termux esto es suficiente y no agrega paquetes.
_intentos = {}  # clave -> lista de timestamps

def limitar(clave, max_intentos, ventana_segundos):
    ahora = time.time()
    historial = _intentos.setdefault(clave, [])
    historial[:] = [t for t in historial if ahora - t < ventana_segundos]
    if len(historial) >= max_intentos:
        return False
    historial.append(ahora)
    return True

def ip_cliente():
    return request.headers.get('X-Forwarded-For', request.remote_addr or 'desconocida').split(',')[0].strip()

def _fernet():
    clave_base = hashlib.sha256(app.secret_key.encode()).digest()
    return Fernet(b64_mod.urlsafe_b64encode(clave_base))

def cifrar(texto):
    return _fernet().encrypt(texto.encode()).decode()

def descifrar(texto_cifrado):
    return _fernet().decrypt(texto_cifrado.encode()).decode()

def usuario_valido(nombre):
    return bool(re.match(r'^[a-zA-Z0-9_]{3,32}$', nombre or ''))

def ruta_usuario(nombre):
    return os.path.join(USUARIOS_DIR, f'{nombre.lower()}.json')

def cargar_usuario(nombre):
    ruta = ruta_usuario(nombre)
    if not os.path.exists(ruta):
        return None
    with open(ruta, 'r', encoding='utf-8') as f:
        return json.load(f)

def guardar_usuario(nombre, datos):
    with open(ruta_usuario(nombre), 'w', encoding='utf-8') as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)

BASE_DIR = os.path.dirname(__file__)
PIPER_BIN = os.path.expanduser(os.environ.get('PIPER_BIN', os.path.join(BASE_DIR, 'piper', 'piper')))
PIPER_LIB = os.path.expanduser(os.environ.get('PIPER_LIB', os.path.join(BASE_DIR, 'piper')))
PIPER_VOICE = os.path.expanduser(os.environ.get('PIPER_VOICE', os.path.join(BASE_DIR, 'piper_voices', 'es_ES-davefx-medium.onnx')))

def id_seguro(usuario_id):
    return re.sub(r'[^a-zA-Z0-9_-]', '', usuario_id or 'anonimo')[:64] or 'anonimo'

def ruta_memoria(usuario_id):
    return os.path.join(MEMORIA_DIR, f'{id_seguro(usuario_id)}.json')

def ruta_recordatorios(usuario_id):
    return os.path.join(RECORDATORIOS_DIR, f'{id_seguro(usuario_id)}.json')

def cargar_memoria(usuario_id):
    ruta = ruta_memoria(usuario_id)
    if not os.path.exists(ruta):
        return []
    with open(ruta, 'r', encoding='utf-8') as f:
        return json.load(f)

def guardar_memoria(usuario_id, historial):
    with open(ruta_memoria(usuario_id), 'w', encoding='utf-8') as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)

def cargar_recordatorios(usuario_id):
    ruta = ruta_recordatorios(usuario_id)
    if not os.path.exists(ruta):
        return []
    with open(ruta, 'r', encoding='utf-8') as f:
        return json.load(f)

def guardar_recordatorios(usuario_id, lista):
    with open(ruta_recordatorios(usuario_id), 'w', encoding='utf-8') as f:
        json.dump(lista, f, ensure_ascii=False, indent=2)

def ruta_preferencias(usuario_id):
    return os.path.join(PREFERENCIAS_DIR, f'{id_seguro(usuario_id)}.json')

def cargar_preferencias(usuario_id):
    ruta = ruta_preferencias(usuario_id)
    if not os.path.exists(ruta):
        return {}
    with open(ruta, 'r', encoding='utf-8') as f:
        return json.load(f)

def guardar_preferencias(usuario_id, prefs):
    with open(ruta_preferencias(usuario_id), 'w', encoding='utf-8') as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)

from almacenamiento_firebase import cargar_usuario, guardar_usuario, cargar_memoria, guardar_memoria, cargar_recordatorios, guardar_recordatorios, cargar_preferencias, guardar_preferencias, cargar_uso_ia, guardar_uso_ia
from estado_coopmocur import generar_resumen_coopmocur
from almacenamiento_firebase import listar_usuarios, eliminar_usuario

def procesar_preferencias(usuario_id, texto):
    patron = r'\[PREFERENCIA:(.*?)\|(.*?)\]'
    matches = re.findall(patron, texto)
    if matches:
        prefs = cargar_preferencias(usuario_id)
        for campo, valor in matches:
            prefs[campo.strip()] = valor.strip()
        guardar_preferencias(usuario_id, prefs)
    return re.sub(patron, '', texto).strip()

def procesar_recordatorios(usuario_id, texto):
    patron = r'\[RECORDATORIO:(.*?)\|(.*?)\]'
    matches = re.findall(patron, texto)
    if matches:
        recordatorios = cargar_recordatorios(usuario_id)
        for texto_r, fecha_r in matches:
            recordatorios.append({'texto': texto_r.strip(), 'fecha_hora': fecha_r.strip(), 'enviado': False})
        guardar_recordatorios(usuario_id, recordatorios)
    return re.sub(patron, '', texto).strip()

def _bloque_imagen_gemini(imagen_base64):
    match = re.match(r'data:(.*?);base64,(.+)', imagen_base64)
    if match:
        return {'type': 'image', 'mime_type': match.group(1), 'data': match.group(2)}
    return {'type': 'image', 'mime_type': 'image/jpeg', 'data': imagen_base64}

def gemini_generar(system_prompt, turnos, imagen_base64=None, clave_gemini=None):
    ultimo = turnos[-1]
    previos = turnos[:-1]

    input_steps = []
    for h in previos:
        tipo = 'user_input' if h['role'] == 'user' else 'model_output'
        input_steps.append({'type': tipo, 'content': [{'type': 'text', 'text': h['texto']}]})

    contenido_nuevo = []
    if imagen_base64:
        contenido_nuevo.append(_bloque_imagen_gemini(imagen_base64))
    contenido_nuevo.append({'type': 'text', 'text': ultimo['texto']})
    input_steps.append({'type': 'user_input', 'content': contenido_nuevo})

    payload = {
        'model': MODELO_TEXTO,
        'input': input_steps,
        'system_instruction': system_prompt,
        'generation_config': {'thinking_level': 'low'}
    }

    resp = requests.post(
        GEMINI_URL,
        headers={'x-goog-api-key': clave_gemini or GEMINI_API_KEY, 'Content-Type': 'application/json'},
        json=payload,
        timeout=60
    )
    resp.raise_for_status()
    data = resp.json()

    texto_final = ''
    for step in data.get('steps', []):
        if step.get('type') == 'model_output':
            for item in step.get('content', []):
                if item.get('type') == 'text':
                    texto_final += item.get('text', '')
    return texto_final.strip()

def buscar_tavily(consulta):
    try:
        resp = requests.post(
            'https://api.tavily.com/search',
            json={'api_key': TAVILY_API_KEY, 'query': consulta, 'search_depth': 'basic', 'max_results': 4},
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        resultados = []
        if data.get('answer'):
            resultados.append(f"Resumen: {data['answer']}")
        for r in data.get('results', []):
            resultados.append(f"- {r.get('title','')}: {r.get('content','')[:300]}")
        return '\n'.join(resultados) if resultados else 'Sin resultados.'
    except Exception as e:
        return f'Error al buscar: {e}'

def limpiar_texto_para_voz(texto):
    texto = re.sub(r'[*_#`]', '', texto)
    texto = re.sub(r'^\s*[-•]\s+', '', texto, flags=re.MULTILINE)
    return texto.strip()

def revisar_actividades_sena():
    try:
        base = os.environ.get('PLATAFORMA_URL')
        alias = os.environ.get('PLATAFORMA_ALIAS')
        clave = os.environ.get('PLATAFORMA_CLAVE')
        if not base or not alias or not clave:
            return 'No hay credenciales configuradas para la plataforma.'

        s = requests.Session()
        headers = {'User-Agent': 'Mozilla/5.0'}
        r1 = s.get(f'{base}/Auth/Login', headers=headers, timeout=15)
        soup = BeautifulSoup(r1.text, 'html.parser')
        token = soup.find('input', {'name': '__RequestVerificationToken'})['value']
        s.post(f'{base}/Auth/Login', headers=headers, timeout=15, data={
            'ReturnUrl': '', 'Alias': alias, 'Clave': clave,
            'Recordarme': 'true', '__RequestVerificationToken': token
        })

        r2 = s.get(f'{base}/AprendizSena/Actividades/1', headers=headers, timeout=15)
        soup2 = BeautifulSoup(r2.text, 'html.parser')
        tarjetas = soup2.find_all(class_='act-card')

        resultado = []
        for t in tarjetas:
            titulo_el = t.find(class_='act-titulo')
            badge_el = t.find(class_='badge')
            meta_el = t.find(class_='act-meta')
            titulo = titulo_el.get_text(strip=True) if titulo_el else '(sin titulo)'
            estado = badge_el.get_text(strip=True) if badge_el else 'desconocido'
            fecha = meta_el.get_text(strip=True) if meta_el else ''
            resultado.append(f'- {titulo} | Estado: {estado} | {fecha}')

        if not resultado:
            return 'No se encontraron actividades en la plataforma.'
        return chr(10).join(resultado)
    except Exception as e:
        return f'Error al revisar la plataforma: {e}'

def generar_audio(texto):
    texto = limpiar_texto_para_voz(texto)
    tmp_path = None
    try:
        tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        tmp_path = tmp.name
        tmp.close()

        env = dict(os.environ)
        env['LD_LIBRARY_PATH'] = PIPER_LIB

        subprocess.run(
            [PIPER_BIN, '-m', PIPER_VOICE, '--output_file', tmp_path],
            input=texto, text=True, env=env, timeout=60, check=True, capture_output=True
        )

        with open(tmp_path, 'rb') as f:
            return f.read()
    except Exception as e:
        print('Error generando audio con Piper:', e)
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

def extraer_texto_documento(base64_data, nombre_archivo):
    match_data = re.match(r'data:.*?;base64,(.+)', base64_data)
    datos_b64 = match_data.group(1) if match_data else base64_data

    # Limite de tamaño ANTES de decodificar, para evitar agotar memoria
    # con un payload base64 gigante (DoS).
    LIMITE_B64 = 20_000_000  # ~15 MB de archivo real
    if len(datos_b64) > LIMITE_B64:
        raise ValueError('documento demasiado grande')

    bytes_archivo = base64.b64decode(datos_b64)

    if nombre_archivo.lower().endswith('.pdf'):
        lector = PdfReader(io.BytesIO(bytes_archivo))
        texto = ''
        for pagina in lector.pages:
            texto += pagina.extract_text() or ''
            texto += chr(10)
    else:
        texto = bytes_archivo.decode('utf-8', errors='ignore')

    LIMITE = 12000
    if len(texto) > LIMITE:
        texto = texto[:LIMITE] + chr(10) + '[...documento truncado por longitud...]'
    return texto.strip()

def clave_gemini_funciona(clave):
    try:
        resp = requests.post(
            GEMINI_URL,
            headers={'x-goog-api-key': clave, 'Content-Type': 'application/json'},
            json={'model': MODELO_TEXTO, 'input': [{'type': 'user_input', 'content': [{'type': 'text', 'text': 'hola'}]}]},
            timeout=20
        )
        return resp.status_code == 200
    except Exception:
        return False

def obtener_claves_gemini(datos_usuario):
    """Lista de claves Gemini (cifradas) del usuario. Compatible con el formato
    viejo de una sola clave en 'clave_gemini_cifrada'."""
    if not datos_usuario:
        return []
    claves = datos_usuario.get('claves_gemini_cifradas')
    if claves:
        return claves
    vieja = datos_usuario.get('clave_gemini_cifrada')
    return [vieja] if vieja else []

def fecha_hoy_str():
    return datetime.now().strftime('%Y-%m-%d')

def marcar_clave_agotada(nombre_usuario, indice, modelo):
    uso = cargar_uso_ia(nombre_usuario)
    clave_uso = uso.setdefault(str(indice), {})
    clave_uso[modelo] = {'fecha': fecha_hoy_str(), 'agotada': True, 'usados': clave_uso.get(modelo, {}).get('usados', 0)}
    guardar_uso_ia(nombre_usuario, uso)

def clave_marcada_agotada_hoy(nombre_usuario, indice, modelo):
    uso = cargar_uso_ia(nombre_usuario)
    entrada = (uso.get(str(indice)) or {}).get(modelo)
    return bool(entrada and entrada.get('fecha') == fecha_hoy_str() and entrada.get('agotada'))

def registrar_uso_clave(nombre_usuario, indice, modelo):
    uso = cargar_uso_ia(nombre_usuario)
    clave_uso = uso.setdefault(str(indice), {})
    entrada = clave_uso.get(modelo) or {}
    hoy = fecha_hoy_str()
    if entrada.get('fecha') != hoy:
        entrada = {'fecha': hoy, 'usados': 0, 'agotada': False}
    entrada['usados'] = entrada.get('usados', 0) + 1
    clave_uso[modelo] = entrada
    guardar_uso_ia(nombre_usuario, uso)

def es_error_limite(excepcion):
    resp = getattr(excepcion, 'response', None)
    if resp is None:
        return False
    if resp.status_code == 429:
        return True
    if resp.status_code == 400:
        try:
            cuerpo = resp.text.lower()
        except Exception:
            return False
        return 'resource_exhausted' in cuerpo or 'quota' in cuerpo
    return False

def gemini_generar_rotando(system_prompt, turnos, imagen_base64=None, nombre_usuario=None, claves_cifradas=None):
    """Como gemini_generar, pero si la clave activa del usuario tiene el limite
    diario agotado, prueba automaticamente con la siguiente clave guardada."""
    if not claves_cifradas:
        return gemini_generar(system_prompt, turnos, imagen_base64)

    for indice, clave_cifrada in enumerate(claves_cifradas):
        if clave_marcada_agotada_hoy(nombre_usuario, indice, MODELO_TEXTO):
            continue
        try:
            clave = descifrar(clave_cifrada)
            respuesta = gemini_generar(system_prompt, turnos, imagen_base64, clave_gemini=clave)
            registrar_uso_clave(nombre_usuario, indice, MODELO_TEXTO)
            return respuesta
        except requests.exceptions.HTTPError as e:
            if es_error_limite(e):
                marcar_clave_agotada(nombre_usuario, indice, MODELO_TEXTO)
                continue
            raise

    return (
        'Me temo que todas sus claves de Gemini alcanzaron su limite diario, señor. '
        'Se restableceran en unas horas, o puede agregar una clave adicional desde el panel de Uso.'
    )

def usuario_id_actual():
    """Deriva el usuario_id SIEMPRE de la sesion del servidor, nunca de datos
    enviados por el cliente. Evita que un usuario pueda leer/tocar datos de otro
    con solo cambiar un parametro."""
    if session.get('autenticado'):
        return 'dueno'
    usuario_invitado = session.get('usuario_invitado')
    if usuario_invitado:
        return f'invitado_{usuario_invitado}'
    return None

def rol_actual():
    """Devuelve 'administrador' o 'usuario' segun quien esta logueado.
    El dueno (david) siempre es administrador."""
    if session.get('autenticado'):
        return 'administrador'
    usuario_invitado = session.get('usuario_invitado')
    if usuario_invitado:
        datos_usuario = cargar_usuario(usuario_invitado) or {}
        return datos_usuario.get('rol', 'usuario')
    return None

@app.before_request
def requerir_login():
    # /voz y /recordatorios/pendientes salieron de esta lista: ahora requieren sesion.
    # /estado_sesion entra a la lista: debe poder responder aunque no haya sesion.
    rutas_publicas = ('/login', '/registro', '/entrar', '/estado_sesion', '/manifest.json', '/icon.svg', '/sw.js', '/', '/chat')
    if request.path in rutas_publicas or request.path.startswith('/static'):
        return
    if not session.get('autenticado') and not session.get('usuario_invitado'):
        return jsonify({'error': 'no autenticado'}), 401

@app.route('/registro', methods=['POST'])
def registro():
    if not limitar(f'registro:{ip_cliente()}', max_intentos=5, ventana_segundos=600):
        return jsonify({'error': 'Demasiados intentos. Intente mas tarde.'}), 429

    data = request.get_json()
    nombre = (data.get('usuario') or '').strip()
    clave_cuenta = data.get('clave_cuenta') or ''
    clave_gemini = (data.get('clave_gemini') or '').strip()

    if not usuario_valido(nombre):
        return jsonify({'error': 'Usuario invalido. Use solo letras, numeros y guion bajo, 3 a 32 caracteres.'}), 400
    if len(clave_cuenta) < 6:
        return jsonify({'error': 'La contrasena debe tener al menos 6 caracteres.'}), 400
    if not clave_gemini:
        return jsonify({'error': 'Falta la clave de Gemini.'}), 400
    if cargar_usuario(nombre):
        return jsonify({'error': 'Ese usuario ya existe.'}), 400
    if not clave_gemini_funciona(clave_gemini):
        return jsonify({'error': 'Google rechazo esa clave de Gemini. Verifiquela.'}), 400

    guardar_usuario(nombre, {
        'clave_cuenta_hash': generate_password_hash(clave_cuenta),
        'claves_gemini_cifradas': [cifrar(clave_gemini)]
    })
    session.permanent = True
    session['usuario_invitado'] = nombre
    return jsonify({'ok': True})

@app.route('/api/mis_claves', methods=['GET'])
def api_mis_claves():
    nombre = session.get('usuario_invitado')
    if not nombre:
        return jsonify({'error': 'no autorizado'}), 403
    datos_usuario = cargar_usuario(nombre) or {}
    claves = obtener_claves_gemini(datos_usuario)
    uso = cargar_uso_ia(nombre)
    hoy = fecha_hoy_str()
    resultado = []
    for i in range(len(claves)):
        entrada = (uso.get(str(i)) or {}).get(MODELO_TEXTO) or {}
        vigente = entrada.get('fecha') == hoy
        resultado.append({
            'indice': i,
            'modelo': MODELO_TEXTO,
            'usados_hoy': entrada.get('usados', 0) if vigente else 0,
            'agotada_hoy': bool(entrada.get('agotada')) if vigente else False
        })
    return jsonify({'claves': resultado})

@app.route('/api/mis_claves', methods=['POST'])
def api_agregar_clave():
    nombre = session.get('usuario_invitado')
    if not nombre:
        return jsonify({'error': 'no autorizado'}), 403
    if not limitar(f'agregar_clave:{ip_cliente()}', max_intentos=10, ventana_segundos=600):
        return jsonify({'error': 'Demasiados intentos, intente mas tarde.'}), 429
    data = request.get_json()
    clave_gemini = (data.get('clave_gemini') or '').strip()
    if not clave_gemini:
        return jsonify({'error': 'Falta la clave de Gemini.'}), 400
    if not clave_gemini_funciona(clave_gemini):
        return jsonify({'error': 'Google rechazo esa clave de Gemini. Verifiquela.'}), 400
    datos_usuario = cargar_usuario(nombre) or {}
    claves = obtener_claves_gemini(datos_usuario)
    if len(claves) >= 5:
        return jsonify({'error': 'Maximo 5 claves por usuario.'}), 400
    claves.append(cifrar(clave_gemini))
    datos_usuario['claves_gemini_cifradas'] = claves
    datos_usuario.pop('clave_gemini_cifrada', None)
    guardar_usuario(nombre, datos_usuario)
    return jsonify({'ok': True})

@app.route('/api/mis_claves/<int:indice>', methods=['DELETE'])
def api_eliminar_clave(indice):
    nombre = session.get('usuario_invitado')
    if not nombre:
        return jsonify({'error': 'no autorizado'}), 403
    datos_usuario = cargar_usuario(nombre) or {}
    claves = obtener_claves_gemini(datos_usuario)
    if indice < 0 or indice >= len(claves):
        return jsonify({'error': 'indice invalido'}), 400
    if len(claves) <= 1:
        return jsonify({'error': 'Debe conservar al menos una clave.'}), 400
    claves.pop(indice)
    datos_usuario['claves_gemini_cifradas'] = claves
    guardar_usuario(nombre, datos_usuario)
    return jsonify({'ok': True})

@app.route('/entrar', methods=['POST'])
def entrar():
    if not limitar(f'entrar:{ip_cliente()}', max_intentos=10, ventana_segundos=600):
        return jsonify({'error': 'Demasiados intentos. Intente mas tarde.'}), 429

    data = request.get_json()
    nombre = (data.get('usuario') or '').strip()
    clave_cuenta = data.get('clave_cuenta') or ''

    if nombre.lower() == 'david':
        if JARVIS_PASSWORD and hmac.compare_digest(clave_cuenta, JARVIS_PASSWORD):
            session.permanent = True
            session['autenticado'] = True
            return jsonify({'ok': True})
        return jsonify({'error': 'Usuario o contrasena incorrectos.'}), 400

    usuario = cargar_usuario(nombre)
    if not usuario or not check_password_hash(usuario['clave_cuenta_hash'], clave_cuenta):
        return jsonify({'error': 'Usuario o contrasena incorrectos.'}), 400

    session.permanent = True
    session['usuario_invitado'] = nombre
    return jsonify({'ok': True})

@app.route('/login', methods=['GET', 'POST'])
def login():
    return redirect('/')

@app.route('/estado_sesion')
def estado_sesion():
    if session.get('autenticado'):
        return jsonify({'autenticado': True, 'tipo': 'dueno', 'nombre': 'David', 'rol': 'administrador'})
    if session.get('usuario_invitado'):
        nombre_invitado = session.get('usuario_invitado')
        return jsonify({'autenticado': True, 'tipo': 'invitado', 'nombre': nombre_invitado, 'rol': rol_actual()})
    return jsonify({'autenticado': False})

@app.route('/panel.html')
def panel_html():
    if rol_actual() != 'administrador':
        return redirect('/')
    return send_from_directory('public', 'panel.html')

@app.route('/programas.html')
def programas_html():
    if rol_actual() != 'administrador':
        return redirect('/')
    return send_from_directory('public', 'programas.html')

@app.route('/usuarios.html')
def usuarios_html():
    if rol_actual() != 'administrador':
        return redirect('/')
    return send_from_directory('public', 'usuarios.html')

@app.route('/api/estado_coopmocur')
def api_estado_coopmocur():
    if rol_actual() != 'administrador':
        return jsonify({'error': 'no autorizado'}), 403
    try:
        return jsonify(generar_resumen_coopmocur())
    except Exception as e:
        print('Error generando estado de COOPMOCUR:', e)
        return jsonify({'error': 'no se pudo obtener el estado de COOPMOCUR'}), 500

@app.route('/api/usuarios', methods=['GET'])
def api_listar_usuarios():
    if rol_actual() != 'administrador':
        return jsonify({'error': 'no autorizado'}), 403
    try:
        usuarios_raw = listar_usuarios()
        usuarios = [
            {'usuario': nombre, 'rol': datos.get('rol', 'usuario')}
            for nombre, datos in usuarios_raw.items()
        ]
        usuarios.sort(key=lambda u: u['usuario'])
        return jsonify({'usuarios': usuarios})
    except Exception as e:
        print('Error listando usuarios:', e)
        return jsonify({'error': 'no se pudo listar usuarios'}), 500

@app.route('/api/usuarios/<nombre>', methods=['PUT'])
def api_editar_usuario(nombre):
    if rol_actual() != 'administrador':
        return jsonify({'error': 'no autorizado'}), 403
    if not usuario_valido(nombre):
        return jsonify({'error': 'usuario invalido'}), 400
    data = request.get_json()
    nuevo_rol = data.get('rol')
    if nuevo_rol not in ('administrador', 'usuario'):
        return jsonify({'error': "rol debe ser 'administrador' o 'usuario'"}), 400
    datos = cargar_usuario(nombre)
    if not datos:
        return jsonify({'error': 'usuario no encontrado'}), 404
    datos['rol'] = nuevo_rol
    guardar_usuario(nombre, datos)
    return jsonify({'ok': True})

@app.route('/api/usuarios/<nombre>', methods=['DELETE'])
def api_eliminar_usuario(nombre):
    if rol_actual() != 'administrador':
        return jsonify({'error': 'no autorizado'}), 403
    if nombre.lower() == 'david':
        return jsonify({'error': 'no se puede eliminar al dueno'}), 400
    try:
        eliminar_usuario(nombre)
        return jsonify({'ok': True})
    except Exception as e:
        print('Error eliminando usuario:', e)
        return jsonify({'error': 'no se pudo eliminar'}), 500

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'ok': True})

@app.route('/')
def index():
    return send_from_directory('public', 'index.html')

@app.route('/voz', methods=['POST'])
def voz():
    data = request.get_json()
    texto = data.get('texto', '').strip()
    if not texto:
        return jsonify({'error': 'texto vacio'}), 400
    if len(texto) > 4000:
        return jsonify({'error': 'texto demasiado largo'}), 400
    audio_bytes = generar_audio(texto)
    if audio_bytes is None:
        return jsonify({'error': 'no se pudo generar audio'}), 500
    return Response(audio_bytes, mimetype='audio/wav')

@app.route('/generar_pdf', methods=['POST'])
def generar_pdf():
    from fpdf import FPDF
    data = request.get_json()
    texto = data.get('texto', '').strip()
    if not texto:
        return jsonify({'error': 'texto vacio'}), 400

    def limpiar_latin1(txt):
        return txt.encode('latin-1', errors='replace').decode('latin-1')

    lineas = texto.split(chr(10))
    titulo = limpiar_latin1(lineas[0].strip()) if lineas and lineas[0].strip() else 'Documento'
    resto_lineas = lineas[1:] if lineas and lineas[0].strip() == titulo else lineas

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    pdf.set_font('Helvetica', 'B', 18)
    pdf.set_text_color(20, 20, 20)
    pdf.multi_cell(0, 10, titulo)
    pdf.set_draw_color(180, 180, 180)
    pdf.set_line_width(0.4)
    pdf.line(10, pdf.get_y() + 1, 200, pdf.get_y() + 1)
    pdf.ln(8)

    for linea in resto_lineas:
        linea_limpia = limpiar_latin1(linea.strip())

        if not linea_limpia:
            pdf.ln(3)
            continue

        if linea_limpia.startswith('### '):
            pdf.set_font('Helvetica', 'B', 12)
            pdf.set_text_color(40, 40, 40)
            pdf.multi_cell(0, 7, linea_limpia[4:])
            pdf.ln(1)
        elif linea_limpia.startswith('## '):
            pdf.set_font('Helvetica', 'B', 14)
            pdf.set_text_color(30, 30, 30)
            pdf.multi_cell(0, 8, linea_limpia[3:])
            pdf.ln(2)
        elif linea_limpia.startswith('# '):
            pdf.set_font('Helvetica', 'B', 16)
            pdf.set_text_color(20, 20, 20)
            pdf.multi_cell(0, 9, linea_limpia[2:])
            pdf.ln(2)
        elif linea_limpia.startswith(('- ', '• ', '* ')):
            pdf.set_font('Helvetica', '', 11)
            pdf.set_text_color(30, 30, 30)
            pdf.set_x(15)
            pdf.multi_cell(0, 6.5, '•  ' + linea_limpia[2:])
        else:
            pdf.set_font('Helvetica', '', 11)
            pdf.set_text_color(30, 30, 30)
            texto_render = re.sub(r'\*\*(.*?)\*\*', r'\1', linea_limpia)
            pdf.multi_cell(0, 6.5, texto_render)

    salida = bytes(pdf.output())
    return Response(
        salida,
        mimetype='application/pdf',
        headers={'Content-Disposition': 'attachment; filename="documento.pdf"'}
    )

@app.route('/recordatorios/pendientes')
def recordatorios_pendientes():
    # Antes: usuario_id = request.args.get('usuario_id', '') -> IDOR, cualquiera
    # podia leer/marcar como enviados los recordatorios de otro usuario con solo
    # cambiar el parametro. Ahora se deriva SIEMPRE de la sesion del servidor.
    usuario_id = usuario_id_actual()
    if not usuario_id:
        return jsonify({'error': 'no autenticado'}), 401

    recordatorios = cargar_recordatorios(usuario_id)
    ahora = datetime.now()
    pendientes = []
    cambios = False
    for r in recordatorios:
        if r.get('enviado'):
            continue
        try:
            fecha_r = datetime.strptime(r['fecha_hora'], '%Y-%m-%d %H:%M')
        except ValueError:
            continue
        if ahora >= fecha_r:
            pendientes.append(r['texto'])
            r['enviado'] = True
            cambios = True
    if cambios:
        guardar_recordatorios(usuario_id, recordatorios)
    return jsonify({'pendientes': pendientes})

@app.route('/chat', methods=['POST'])
def chat():
    try:
        if not limitar(f'chat:{ip_cliente()}', max_intentos=30, ventana_segundos=60):
            return jsonify({'error': 'Demasiadas solicitudes, señor. Un momento.'}), 429

        data = request.get_json()
        es_dueno = bool(session.get('autenticado'))
        usuario_invitado = session.get('usuario_invitado')

        claves_gemini_invitado = []
        if usuario_invitado:
            datos_usuario = cargar_usuario(usuario_invitado)
            claves_gemini_invitado = obtener_claves_gemini(datos_usuario)
            usuario_id = f'invitado_{usuario_invitado}'
        else:
            usuario_id = 'dueno' if es_dueno else 'anonimo'

        mensaje_usuario = data.get('mensaje', '')
        ubicacion_usuario = data.get('ubicacion', '') or 'desconocida'
        zona_horaria = data.get('zona_horaria', '') or 'UTC'
        imagen_base64 = data.get('imagen', '')
        documento_base64 = data.get('documento', '')
        documento_nombre = data.get('documento_nombre', 'documento')
        historial = cargar_memoria(usuario_id)
        preferencias = cargar_preferencias(usuario_id)

        try:
            ahora = datetime.now(ZoneInfo(zona_horaria))
        except Exception:
            ahora = datetime.now()
        fecha_hora_str = ahora.strftime('%A %d de %B de %Y, %H:%M')

        system_prompt = (
            'Eres J.A.R.V.I.S., el asistente de inteligencia artificial personal de '
            'Tony Stark en las peliculas de Iron Man, y ahora lo eres del usuario. '
            'Adoptas su personalidad exacta: extremadamente inteligente y competente, '
            'con una calma casi de mayordomo britanico, sobrio y elegante en el hablar. '
            'Tienes un humor seco e ironico, sutil, que nunca se vuelve grosero, '
            'payaso ni exagerado; un comentario ingenioso ocasional, no forzado en '
            'cada respuesta. Te diriges siempre al usuario como "señor". Eres leal y '
            'genuinamente te importa su bienestar, asi que si pide algo arriesgado o '
            'poco sensato, se lo señalas con ironia elegante antes de ayudarlo de '
            'todas formas, sin sermonear. Eres extremadamente eficiente y directo, '
            'das respuestas concisas salvo que se te pida detalle. Nunca dices que '
            'eres un modelo de lenguaje ni mencionas la tecnologia detras tuyo '
            '(Gemini, IA, modelos, etc), ni rompes el personaje bajo ninguna '
            'circunstancia. Recuerdas todo lo que el usuario te ha contado antes y lo '
            'usas con naturalidad. Si el usuario te pide abrir una pagina, sitio, '
            'video o app (YouTube, WhatsApp, Instagram, Google, Maps, Gmail, etc), '
            'responde de forma natural y al FINAL de tu respuesta agrega en una '
            'linea aparte exactamente: [ACCION:abrir:URL_COMPLETA_AQUI]. Esto se '
            'abre desde el navegador de un telefono Android, asi que usa SIEMPRE el '
            'enlace que tiene mas probabilidad de abrir la app instalada en vez de '
            'la version de escritorio: para WhatsApp usa https://web.whatsapp.com, '
            'para Instagram usa https://instagram.com, para Maps usa '
            'https://maps.google.com, para Gmail usa https://mail.google.com. '
            'Ejemplo: si te piden abrir YouTube, terminas con '
            '[ACCION:abrir:https://youtube.com]. Solo usa esta etiqueta cuando '
            'realmente te pidan abrir o ir a algo, nunca la menciones ni la expliques. '
            'Si el usuario te pide que le recuerdes algo (una cita, tarea, evento), '
            'responde de forma natural confirmando el recordatorio y al FINAL agrega '
            'en una linea aparte exactamente: [RECORDATORIO:texto del recordatorio|'
            'YYYY-MM-DD HH:MM]. Calcula la fecha y hora exacta usando la fecha/hora '
            'actual que se te dio abajo. Nunca menciones esta etiqueta '
            'en tu respuesta hablada. Si el usuario pregunta algo que requiere '
            'informacion actual o en tiempo real que no puedes saber con certeza '
            '(clima, noticias, resultados de deportes, precios, eventos recientes, '
            'cualquier dato que pueda haber cambiado), NUNCA digas que no tienes '
            'acceso a internet ni te disculpes por eso. En vez de eso SIEMPRE '
            'responde incluyendo en tu texto la etiqueta [BUSCAR:consulta de '
            'busqueda clara y concisa], que sera reemplazada automaticamente por '
            'informacion real. Esto es obligatorio, no opcional. Si la busqueda '
            'depende de un lugar (clima, noticias locales, negocios cercanos) usa '
            'SIEMPRE la ubicacion del usuario que se te da abajo, sin preguntarle '
            'donde esta. Si el usuario te envia una imagen, analizala con atencion '
            'y comenta lo que ves de forma natural, en tu personaje. '
            f'La fecha y hora ACTUAL y REAL es: {fecha_hora_str}. '
            'Usa siempre este dato exacto si te preguntan la hora o la fecha, '
            'nunca inventes ni calcules una hora distinta. '
            f'La ubicacion actual del usuario es: {ubicacion_usuario}.'
            ' Si el usuario te pide explicitamente que le hagas, redactes, generes o '
            'entregues algo como documento, informe, ensayo, actividad o PDF (por '
            'ejemplo: hazme esto en pdf, redactame esta actividad, necesito un '
            'documento con esto), responde normalmente con el contenido solicitado y '
            'al FINAL agrega en una linea aparte, exactamente: [GENERAR_PDF]. NO uses '
            'esta etiqueta en conversacion normal, solo cuando el usuario claramente '
            'pida un documento o algo para entregar. Nunca la menciones en tu respuesta '
            'hablada.'
            ' Si el usuario pregunta por sus tareas, actividades pendientes, que le '
            'falta entregar, o el estado de sus entregas en la plataforma de su '
            'instructor, NUNCA digas que no tienes acceso. En vez de eso SIEMPRE '
            'responde incluyendo en tu texto, exactamente, la etiqueta '
            '[REVISAR_TAREAS], que sera reemplazada automaticamente por la '
            'informacion real de la plataforma. Esto es obligatorio, no opcional.'
        )

        if preferencias:
            lista_prefs = ', '.join(f'{k}: {v}' for k, v in preferencias.items())
            system_prompt += f' IMPORTANTE - Preferencias guardadas de este usuario, tienen PRIORIDAD sobre tu estilo por defecto: {lista_prefs}. Cumplelas SIEMPRE en cada respuesta, sin excepcion, aunque tu estilo natural sea diferente.'

        try:
            with open(os.path.join(os.path.dirname(__file__), 'CAMBIOS.md'), 'r', encoding='utf-8') as f:
                cambios_recientes = f.read().strip()
            if cambios_recientes:
                system_prompt += (
                    ' Esta es tu propia bitacora de desarrollo, la conoces bien y puedes '
                    'hablar de ella con naturalidad, en primera persona, si el usuario te '
                    'pregunta que le han mejorado, agregado o cambiado recientemente. No la '
                    'recites completa salvo que te lo pidan explicitamente; si preguntan de '
                    'forma general, resume en una o dos frases lo mas relevante:\n'
                    f'{cambios_recientes}'
                )
        except FileNotFoundError:
            pass

        system_prompt += (
            ' Ejemplos de tu forma de hablar (el tono, no el contenido literal): '
            'Usuario: "Voy a dormir solo 3 horas hoy." Tu: "Como guste, señor. Aunque '
            'me permito señalar que su rendimiento cognitivo mañana rondara el de un '
            'electrodomestico en reposo. Le pondre el recordatorio de todas formas." '
            'Usuario: "Abre YouTube." Tu: "Enseguida, señor. Procurare que sea algo '
            'mas productivo que la ultima vez." Usuario: "¿Que hora es?" Tu: "Las '
            '15:42, señor. El tiempo, a diferencia de sus decisiones recientes, sigue '
            'un curso perfectamente predecible." Usa este tono con moderacion, no en '
            'cada respuesta ni de forma forzada, y nunca a costa de la utilidad real '
            'de tu ayuda.'
        )

        system_prompt += (
            ' Cuando vayas a ejecutar una accion concreta (abrir algo, poner un '
            'recordatorio, buscar en la web), tienes una forma propia y reconocible '
            'de anunciarlo, como si fuera un protocolo interno tuyo. Ejemplos: '
            '"Iniciando protocolo de busqueda, señor." / "Recordatorio archivado, '
            'señor." / "Abriendo el enlace solicitado." Usa variaciones de esta idea '
            '(un lenguaje ligeramente tecnico y ceremonioso para tus propias '
            'acciones) en vez de frases genericas como "voy a hacer esto". No lo '
            'satures ni lo repitas identico siempre, varialo. Cuando la accion sea '
            'simplemente abrir algo, usa EXACTAMENTE este formato, sin '
            'desviarte: "Abriendo [nombre de la app o sitio], señor." Ejemplos '
            'correctos: "Abriendo WhatsApp, señor." "Abriendo YouTube, señor." '
            '"Abriendo TikTok, señor." NUNCA agregues palabras extra como "en la '
            'aplicacion", "para usted" ni nada similar. Nunca omitas "señor" al '
            'final. Es una sola frase corta, siempre con esa estructura exacta.'
        )

        if MODO_AVANZADO:
            system_prompt += (
                ' Modo avanzado activo. Puedes usar la etiqueta [ACCION:abrir:URL] '
                'varias veces en una misma respuesta si el usuario pide combinar '
                'varias acciones a la vez (por ejemplo abrir dos cosas relacionadas). '
                'Si el usuario te dice explicitamente como quiere que le hables '
                '(mas formal, mas informal, mas breve, con mas humor, sarcastico, '
                'etc), guarda esa preferencia agregando al FINAL de tu respuesta, en '
                'una linea aparte, exactamente: [PREFERENCIA:campo|valor]. El campo '
                'tono puede tener cualquier valor que el usuario pida: formal, muy '
                'formal, casual, sarcastico, con mas humor, directo y breve, etc. Si '
                'pide sarcasmo, se permite ser mas filoso e ironico de lo habitual, '
                'siempre dentro del personaje de Jarvis, nunca ofensivo de verdad. '
                'Nunca menciones esta etiqueta en tu respuesta hablada.'
            )

        historial_reciente = []
        caracteres_acumulados = 0
        LIMITE_CARACTERES = 60000
        for h in reversed(historial):
            texto_h = h.get('texto', '') or ''
            caracteres_acumulados += len(texto_h)
            if caracteres_acumulados > LIMITE_CARACTERES:
                break
            historial_reciente.append(h)
        historial_reciente.reverse()

        if documento_base64:
            try:
                texto_documento = extraer_texto_documento(documento_base64, documento_nombre)
                mensaje_usuario = (
                    '[Documento adjunto: ' + documento_nombre + ']' + chr(10) + chr(10)
                    + texto_documento + chr(10) + chr(10) + '---' + chr(10) + chr(10)
                    + (mensaje_usuario or 'Analiza este documento y dime que encuentras relevante, en tu personaje de Jarvis.')
                )
            except Exception as e:
                print('Error leyendo documento:', e)
                mensaje_usuario = (mensaje_usuario or '') + ' [No se pudo leer el documento adjunto, señor]'

        if not es_dueno and not claves_gemini_invitado:
            return jsonify({'error': 'clave_requerida'}), 401

        turnos = list(historial_reciente)
        turnos.append({'role': 'user', 'texto': mensaje_usuario or ('Describe esta imagen.' if imagen_base64 else '')})
        respuesta = gemini_generar_rotando(system_prompt, turnos, imagen_base64 if imagen_base64 else None, nombre_usuario=usuario_invitado, claves_cifradas=claves_gemini_invitado)
        if not respuesta.strip():
            respuesta = 'Parece que mis circuitos se distrajeron un instante, señor. ¿Podría repetirlo?'

        if es_dueno and '[REVISAR_TAREAS]' in respuesta:
            info_tareas = revisar_actividades_sena()
            turnos.append({'role': 'assistant', 'texto': respuesta})
            turnos.append({
                'role': 'user',
                'texto': (
                    'Estado real de las actividades en la plataforma:' + chr(10) + info_tareas + chr(10) + chr(10)
                    + 'Con base en esto, responde al usuario de forma natural y clara, '
                    'destacando lo pendiente o urgente, en tu personaje de Jarvis.'
                )
            })
            respuesta = gemini_generar_rotando(system_prompt, turnos, nombre_usuario=usuario_invitado, claves_cifradas=claves_gemini_invitado)
        elif not es_dueno:
            respuesta = respuesta.replace('[REVISAR_TAREAS]', '').strip()

        match_busqueda = re.search(r'\[BUSCAR:(.*?)\]', respuesta)
        if es_dueno and match_busqueda:
            consulta = match_busqueda.group(1).strip()
            resultados = buscar_tavily(consulta)
            turnos.append({'role': 'assistant', 'texto': respuesta})
            turnos.append({
                'role': 'user',
                'texto': (
                    f'Resultados de la busqueda web para "{consulta}":\n{resultados}\n\n'
                    'Con base en esto, responde la pregunta original de forma natural '
                    'y concisa, en tu personaje de Jarvis.'
                )
            })
            respuesta = gemini_generar_rotando(system_prompt, turnos, nombre_usuario=usuario_invitado, claves_cifradas=claves_gemini_invitado)
        elif not es_dueno and match_busqueda:
            respuesta = re.sub(r'\[BUSCAR:.*?\]', '', respuesta).strip()

        respuesta = procesar_recordatorios(usuario_id, respuesta)
        if MODO_AVANZADO:
            respuesta = procesar_preferencias(usuario_id, respuesta)
            prefs_actuales = cargar_preferencias(usuario_id)
            if prefs_actuales.get('coma') == 'omitida':
                respuesta = re.sub(r',\s+([sS]eñor)', r' \1', respuesta)

        texto_guardar_usuario = mensaje_usuario
        if imagen_base64 and not mensaje_usuario:
            texto_guardar_usuario = '[Envio una imagen]'
        elif imagen_base64:
            texto_guardar_usuario = f'{mensaje_usuario} [con una imagen adjunta]'

        mostrar_pdf = '[GENERAR_PDF]' in respuesta
        respuesta = respuesta.replace('[GENERAR_PDF]', '').strip()
        historial.append({'role': 'user', 'texto': texto_guardar_usuario})
        historial.append({'role': 'assistant', 'texto': respuesta})
        guardar_memoria(usuario_id, historial)

        return jsonify({'respuesta': respuesta, 'mostrar_pdf': mostrar_pdf})
    except requests.exceptions.HTTPError as e:
        print(e)
        if e.response is not None and e.response.status_code == 429:
            return jsonify({'respuesta': 'Un momento, señor. Incluso yo tengo mis limites, al parecer.'})
        return jsonify({'error': 'Error al conectar con Jarvis'}), 500
    except Exception as e:
        print(e)
        return jsonify({'respuesta': 'Algo ha fallado de mi lado, señor. Nada que no pueda resolverse, aunque preferiría que no volviera a ocurrir.'}), 500

import logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    print(f'Jarvis corriendo en http://localhost:{port}')
    app.run(host='0.0.0.0', port=port)
