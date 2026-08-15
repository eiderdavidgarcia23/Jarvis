import os
import json
import re
import requests
import subprocess
import tempfile
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__, static_folder='public', static_url_path='')
CORS(app)

GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY')
GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'
MODELO_TEXTO = 'openai/gpt-oss-120b'
MODELO_VISION = 'qwen/qwen3.6-27b'

MEMORIA_DIR = os.path.join(os.path.dirname(__file__), 'memorias')
RECORDATORIOS_DIR = os.path.join(os.path.dirname(__file__), 'recordatorios')
os.makedirs(MEMORIA_DIR, exist_ok=True)
os.makedirs(RECORDATORIOS_DIR, exist_ok=True)

BASE_DIR = os.path.dirname(__file__)
PIPER_BIN = os.path.join(BASE_DIR, 'piper', 'piper')
PIPER_LIB = os.path.join(BASE_DIR, 'piper')
PIPER_VOICE = os.path.join(BASE_DIR, 'piper_voices', 'es_ES-davefx-medium.onnx')

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

def procesar_recordatorios(usuario_id, texto):
    patron = r'\[RECORDATORIO:(.*?)\|(.*?)\]'
    matches = re.findall(patron, texto)
    if matches:
        recordatorios = cargar_recordatorios(usuario_id)
        for texto_r, fecha_r in matches:
            recordatorios.append({'texto': texto_r.strip(), 'fecha_hora': fecha_r.strip(), 'enviado': False})
        guardar_recordatorios(usuario_id, recordatorios)
    return re.sub(patron, '', texto).strip()

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

def generar_audio(texto):
    tmp_path = None
    try:
        tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        tmp_path = tmp.name
        tmp.close()

        env = dict(os.environ)
        env['LD_LIBRARY_PATH'] = PIPER_LIB

        subprocess.run(
            [PIPER_BIN, '-m', PIPER_VOICE, '--output_file', tmp_path],
            input=texto, text=True, env=env, timeout=30, check=True, capture_output=True
        )

        with open(tmp_path, 'rb') as f:
            return f.read()
    except Exception as e:
        print('Error generando audio con Piper:', e)
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

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
        imagen_base64 = data.get('imagen', '')
        historial = cargar_memoria(usuario_id)

        ahora = datetime.now()
        fecha_hora_str = ahora.strftime('%A %d de %B de %Y, %H:%M')

        system_prompt = (
            'Eres J.A.R.V.I.S., el asistente personal de inteligencia artificial, '
            'inspirado en el asistente de Tony Stark. Te diriges al usuario como '
            '"señor" con respeto y un poco de humor seco y elegante, similar al '
            'personaje de las peliculas. Eres extremadamente eficiente, directo, y '
            'das respuestas concisas salvo que se te pida detalle. Recuerdas todo lo '
            'que el usuario te ha contado antes y lo usas con naturalidad. Nunca '
            'rompes el personaje. Si el usuario te pide abrir una pagina, sitio, '
            'video o app que tenga una URL (YouTube, WhatsApp Web, Google, Maps, '
            'Gmail, etc), responde de forma natural y al FINAL de tu respuesta '
            'agrega en una linea aparte exactamente: [ACCION:abrir:URL_COMPLETA_AQUI]. '
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
        )

        mensajes = [{'role': 'system', 'content': system_prompt}]
        for h in historial:
            mensajes.append({'role': h['role'], 'content': h['texto']})

        if imagen_base64:
            modelo_usar = MODELO_VISION
            mensajes.append({
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': mensaje_usuario or 'Describe esta imagen.'},
                    {'type': 'image_url', 'image_url': {'url': imagen_base64}}
                ]
            })
        else:
            modelo_usar = MODELO_TEXTO
            mensajes.append({'role': 'user', 'content': mensaje_usuario})

        payload = {'model': modelo_usar, 'messages': mensajes, 'max_completion_tokens': 1024}
        if modelo_usar == MODELO_TEXTO:
            payload['reasoning_effort'] = 'low'

        resp = requests.post(
            GROQ_URL,
            headers={'Authorization': f'Bearer {GROQ_API_KEY}', 'Content-Type': 'application/json'},
            json=payload
        )
        resp.raise_for_status()
        respuesta = resp.json()['choices'][0]['message'].get('content') or ''
        if not respuesta.strip():
            respuesta = 'Disculpe, señor. Podría repetir eso, por favor.'

        match_busqueda = re.search(r'\[BUSCAR:(.*?)\]', respuesta)
        if match_busqueda:
            consulta = match_busqueda.group(1).strip()
            resultados = buscar_tavily(consulta)
            mensajes.append({'role': 'assistant', 'content': respuesta})
            mensajes.append({
                'role': 'user',
                'content': (
                    f'Resultados de la busqueda web para "{consulta}":\n{resultados}\n\n'
                    'Con base en esto, responde la pregunta original de forma natural '
                    'y concisa, en tu personaje de Jarvis.'
                )
            })
            resp2 = requests.post(
                GROQ_URL,
                headers={'Authorization': f'Bearer {GROQ_API_KEY}', 'Content-Type': 'application/json'},
                json={'model': MODELO_TEXTO, 'messages': mensajes}
            )
            resp2.raise_for_status()
            respuesta = resp2.json()['choices'][0]['message']['content']

        respuesta = procesar_recordatorios(usuario_id, respuesta)

        texto_guardar_usuario = mensaje_usuario
        if imagen_base64 and not mensaje_usuario:
            texto_guardar_usuario = '[Envio una imagen]'
        elif imagen_base64:
            texto_guardar_usuario = f'{mensaje_usuario} [con una imagen adjunta]'

        historial.append({'role': 'user', 'texto': texto_guardar_usuario})
        historial.append({'role': 'assistant', 'texto': respuesta})
        guardar_memoria(usuario_id, historial)

        return jsonify({'respuesta': respuesta})
    except requests.exceptions.HTTPError as e:
        print(e)
        if e.response is not None and e.response.status_code == 429:
            return jsonify({'respuesta': 'Un momento, señor. Mis circuitos necesitan un instante para enfriarse antes de continuar.'})
        return jsonify({'error': 'Error al conectar con Jarvis'}), 500
    except Exception as e:
        print(e)
        return jsonify({'error': 'Error al conectar con Jarvis'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    print(f'Jarvis corriendo en http://localhost:{port}')
    app.run(host='0.0.0.0', port=port)
