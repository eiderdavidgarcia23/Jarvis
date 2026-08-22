import os
import json
import re
import requests
import subprocess
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import base64
import io
from pypdf import PdfReader
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, send_from_directory, Response, session, redirect
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__, static_folder='public', static_url_path='')
CORS(app)

app.secret_key = os.environ.get('SECRET_KEY', 'clave-temporal-cambiar-en-env')
app.permanent_session_lifetime = timedelta(days=30)
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

def gemini_generar(system_prompt, turnos, imagen_base64=None):
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
        'system_instruction': system_prompt
    }

    resp = requests.post(
        GEMINI_URL,
        headers={'x-goog-api-key': GEMINI_API_KEY, 'Content-Type': 'application/json'},
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

@app.before_request
def requerir_login():
    rutas_publicas = ('/login', '/manifest.json', '/icon.svg', '/sw.js')
    if request.path in rutas_publicas or request.path.startswith('/static'):
        return
    if not session.get('autenticado'):
        if request.path == '/':
            return redirect('/login')
        return jsonify({'error': 'no autenticado'}), 401

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = ''
    if request.method == 'POST':
        clave = request.form.get('clave', '')
        if JARVIS_PASSWORD and clave == JARVIS_PASSWORD:
            session.permanent = True
            session['autenticado'] = True
            return redirect('/')
        error = 'Clave incorrecta, señor.'

    return f'''<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>J.A.R.V.I.S. - Acceso</title>
<style>
  body {{ margin:0; height:100vh; display:flex; align-items:center; justify-content:center;
    background:#05070d; font-family:'Courier New', monospace; }}
  form {{ background:#10151f; border:1px solid #00e5ff33; border-radius:16px; padding:32px;
    width:min(90vw, 320px); text-align:center; }}
  h1 {{ color:#00e5ff; letter-spacing:4px; font-size:20px; margin-bottom:24px; }}
  input {{ width:100%; padding:12px; margin-bottom:12px; border-radius:8px; border:1px solid #00e5ff44;
    background:#1a2332; color:white; font-size:16px; box-sizing:border-box; }}
  button {{ width:100%; padding:12px; border-radius:8px; border:none; background:#00e5ff;
    color:#05070d; font-weight:bold; font-size:16px; }}
  p {{ color:#ff5050; font-size:13px; }}
</style></head><body>
<form method="POST">
  <h1>J.A.R.V.I.S.</h1>
  <input type="password" name="clave" placeholder="Clave de acceso" autofocus>
  <button type="submit">Entrar</button>
  {f'<p>{error}</p>' if error else ''}
</form></body></html>'''

@app.route('/')
def index():
    return send_from_directory('public', 'index.html')

@app.route('/voz', methods=['POST'])
def voz():
    data = request.get_json()
    texto = data.get('texto', '').strip()
    if not texto:
        return jsonify({'error': 'texto vacio'}), 400
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
    usuario_id = request.args.get('usuario_id', '')
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
        data = request.get_json()
        usuario_id = data.get('usuario_id', 'anonimo')
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
        LIMITE_CARACTERES = 4000
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

        turnos = list(historial_reciente)
        turnos.append({'role': 'user', 'texto': mensaje_usuario or ('Describe esta imagen.' if imagen_base64 else '')})

        respuesta = gemini_generar(system_prompt, turnos, imagen_base64 if imagen_base64 else None)
        if not respuesta.strip():
            respuesta = 'Parece que mis circuitos se distrajeron un instante, señor. ¿Podría repetirlo?'

        if '[REVISAR_TAREAS]' in respuesta:
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
            respuesta = gemini_generar(system_prompt, turnos)

        match_busqueda = re.search(r'\[BUSCAR:(.*?)\]', respuesta)
        if match_busqueda:
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
            respuesta = gemini_generar(system_prompt, turnos)

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
