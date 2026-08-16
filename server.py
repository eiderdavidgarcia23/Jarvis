import os
import json
import re
import requests
import subprocess
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo
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
        zona_horaria = data.get('zona_horaria', '') or 'UTC'
        imagen_base64 = data.get('imagen', '')
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
            '(Groq, IA, modelos, etc), ni rompes el personaje bajo ninguna '
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
                '(mas formal, mas informal, mas breve, con mas humor, etc), guarda '
                'esa preferencia agregando al FINAL de tu respuesta, en una linea '
                'aparte, exactamente: [PREFERENCIA:campo|valor]. Ejemplo: si te '
                'dice "hablame de forma mas casual", agregas '
                '[PREFERENCIA:tono|casual]. Nunca menciones esta etiqueta en tu '
                'respuesta hablada.'
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

        payload = {'model': modelo_usar, 'messages': mensajes, 'max_completion_tokens': 1024, 'temperature': 0.85}
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
            respuesta = 'Parece que mis circuitos se distrajeron un instante, señor. ¿Podría repetirlo?'

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
                json={'model': MODELO_TEXTO, 'messages': mensajes, 'temperature': 0.85}
            )
            resp2.raise_for_status()
            respuesta = resp2.json()['choices'][0]['message']['content']

        respuesta = procesar_recordatorios(usuario_id, respuesta)
        if MODO_AVANZADO:
            respuesta = procesar_preferencias(usuario_id, respuesta)
            prefs_actuales = cargar_preferencias(usuario_id)
            if prefs_actuales.get('coma') == 'omitida':
                respuesta = re.sub(r',\s+([sS]eñor)', r' ', respuesta)

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
