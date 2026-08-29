import os
import re
import json
import tempfile
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv()
from flask import Flask, request, jsonify, send_from_directory, Response

from comandos_dispositivo import encender_linterna, apagar_linterna, vibrar, estado_bateria

app = Flask(__name__, static_folder='public', static_url_path='')

# --- Modelo local (llama-server corriendo en el mismo Termux) ---
MODELO_LOCAL_URL = os.environ.get('MODELO_LOCAL_URL', 'http://localhost:8081/v1/chat/completions')

# --- Gemini (API en la nube) ---
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3.5-flash-lite')
GEMINI_URL = f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent'

# --- Groq (respaldo si Gemini se queda sin cuota) ---
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_MODEL = os.environ.get('GROQ_MODEL', 'openai/gpt-oss-120b')
GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'

# --- Memoria simple, un solo usuario (vos), archivo local ---
MEMORIA_PATH = os.path.join(os.path.dirname(__file__), 'memoria_local.json')
MEMORIA_PERSISTENTE_PATH = os.path.join(os.path.dirname(__file__), 'memoria_persistente.json')


def cargar_memoria_persistente():
    if not os.path.exists(MEMORIA_PERSISTENTE_PATH):
        return []
    with open(MEMORIA_PERSISTENTE_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def guardar_memoria_persistente(datos):
    with open(MEMORIA_PERSISTENTE_PATH, 'w', encoding='utf-8') as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


def agregar_recuerdo(texto):
    datos = cargar_memoria_persistente()
    if texto not in datos:
        datos.append(texto)
        guardar_memoria_persistente(datos)


def procesar_recuerdos(respuesta):
    def _guardar(m):
        agregar_recuerdo(m.group(1).strip())
        return ''
    return re.sub(r'\[RECORDAR:\s*(.*?)\]', _guardar, respuesta).strip()


def cargar_memoria():
    if not os.path.exists(MEMORIA_PATH):
        return []
    with open(MEMORIA_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def guardar_memoria(historial):
    with open(MEMORIA_PATH, 'w', encoding='utf-8') as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)


# --- Voz (Piper), igual que antes ---
BASE_DIR = os.path.dirname(__file__)
PIPER_BIN = os.path.expanduser(os.environ.get('PIPER_BIN', os.path.join(BASE_DIR, 'piper', 'piper')))
PIPER_LIB = os.path.expanduser(os.environ.get('PIPER_LIB', os.path.join(BASE_DIR, 'piper')))
PIPER_VOICE = os.path.expanduser(os.environ.get('PIPER_VOICE', os.path.join(BASE_DIR, 'piper_voices', 'es_ES-davefx-medium.onnx')))


def limpiar_texto_para_voz(texto):
    texto = re.sub(r'[*_#`]', '', texto)
    texto = re.sub(r'^\s*[-•]\s+', '', texto, flags=re.MULTILINE)
    return texto.strip()


def generar_audio(texto):
    import subprocess
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
        traceback.print_exc()
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


def generar_gemini(system_prompt, turnos, api_key):
    contenidos = []
    for h in turnos:
        rol = 'user' if h['role'] == 'user' else 'model'
        contenidos.append({'role': rol, 'parts': [{'text': h['texto']}]})

    print(f'[GEMINI] Llamando a {GEMINI_URL} con modelo {GEMINI_MODEL}...')
    resp = requests.post(
        GEMINI_URL,
        params={'key': api_key},
        json={
            'system_instruction': {'parts': [{'text': system_prompt}]},
            'contents': contenidos,
            'generationConfig': {'temperature': 0.7, 'maxOutputTokens': 500}
        },
        timeout=30
    )
    print(f'[GEMINI] Respuesta HTTP: {resp.status_code}')
    if resp.status_code != 200:
        print(f'[GEMINI] Cuerpo del error: {resp.text[:2000]}')
    resp.raise_for_status()
    data = resp.json()
    return data['candidates'][0]['content']['parts'][0]['text'].strip()


def generar_groq(system_prompt, turnos, api_key):
    mensajes = [{'role': 'system', 'content': system_prompt}]
    for h in turnos:
        rol = 'user' if h['role'] == 'user' else 'assistant'
        mensajes.append({'role': rol, 'content': h['texto']})

    print(f'[GROQ] Llamando a {GROQ_URL} con modelo {GROQ_MODEL}...')
    resp = requests.post(
        GROQ_URL,
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        json={
            'model': GROQ_MODEL,
            'messages': mensajes,
            'temperature': 0.7,
            'max_tokens': 500
        },
        timeout=30
    )
    print(f'[GROQ] Respuesta HTTP: {resp.status_code}')
    if resp.status_code != 200:
        print(f'[GROQ] Cuerpo del error: {resp.text[:2000]}')
    resp.raise_for_status()
    data = resp.json()
    return data['choices'][0]['message']['content'].strip()


# --- El cerebro: llama al modelo local en vez de Gemini/Groq ---
def generar_local(system_prompt, turnos):
    mensajes = [{'role': 'system', 'content': system_prompt}]
    for h in turnos:
        rol = 'user' if h['role'] == 'user' else 'assistant'
        mensajes.append({'role': rol, 'content': h['texto']})

    resp = requests.post(
        MODELO_LOCAL_URL,
        json={'messages': mensajes, 'temperature': 0.7, 'max_tokens': 500},
        timeout=120
    )
    resp.raise_for_status()
    data = resp.json()
    return data['choices'][0]['message']['content'].strip()


SYSTEM_PROMPT_BASE = (
    'Eres J.A.R.V.I.S., el asistente de inteligencia artificial personal del '
    'usuario. Adoptas su personalidad de las peliculas de Iron Man: extremadamente '
    'inteligente, calma casi de mayordomo britanico, sobrio y elegante, con humor '
    'seco e ironico sutil. Te diriges siempre al usuario como "señor". Das '
    'respuestas concisas salvo que se te pida detalle. Nunca dices que eres un '
    'modelo de lenguaje. '
    'Cuando el usuario pida abrir una app o sitio web, responde de forma natural '
    'y al FINAL agrega en una linea aparte exactamente: [ACCION:abrir:URL_COMPLETA]. '
    'Cuando el usuario pida encender la linterna, agrega al final: [ACCION:linterna:on]. '
    'Para apagarla: [ACCION:linterna:off]. '
    'Cuando el usuario pida vibrar el celular o le pida tu atencion fisica, agrega: '
    '[ACCION:vibrar]. '
    'Cuando el usuario pregunte por la bateria del celular, agrega exactamente: '
    '[CONSULTAR_BATERIA], y en tu respuesta hablada di que estas revisando, sin '
    'inventar el porcentaje - se te va a dar el dato real despues. '
    'Nunca menciones estas etiquetas de forma literal en tu respuesta hablada. '
    'Cuando en la charla surja algo importante para recordar siempre (nombre, '
    'proyectos, preferencias, datos personales del usuario), agrega en una linea '
    'aparte exactamente: [RECORDAR: el dato en una frase corta]. Usalo solo para '
    'datos que valga la pena recordar para siempre, no para cada mensaje.'
)


def ejecutar_acciones_dispositivo(respuesta):
    """Ejecuta acciones de hardware que estan en la respuesta y las quita del texto."""
    if '[ACCION:linterna:on]' in respuesta:
        encender_linterna()
        respuesta = respuesta.replace('[ACCION:linterna:on]', '').strip()
    if '[ACCION:linterna:off]' in respuesta:
        apagar_linterna()
        respuesta = respuesta.replace('[ACCION:linterna:off]', '').strip()
    if '[ACCION:vibrar]' in respuesta:
        vibrar()
        respuesta = respuesta.replace('[ACCION:vibrar]', '').strip()
    return respuesta


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


@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        mensaje_usuario = data.get('mensaje', '')
        zona_horaria = data.get('zona_horaria', '') or 'UTC'
        imagen_base64 = data.get('imagen', '')  # el modelo local de texto no la usa por ahora

        proveedor = (request.headers.get('X-Proveedor', '') or 'gemini').strip().lower()
        if proveedor not in ('gemini', 'groq'):
            proveedor = 'gemini'

        llave_gemini_navegador = request.headers.get('X-Gemini-Key', '').strip()
        llave_groq_navegador = request.headers.get('X-Groq-Key', '').strip()

        if proveedor == 'groq':
            api_key = llave_groq_navegador or GROQ_API_KEY
            if not api_key:
                return jsonify({'respuesta': 'No tengo una llave de Groq configurada, señor. Agreguela en Ajustes o en el archivo .env.'}), 400
        else:
            api_key = llave_gemini_navegador or GEMINI_API_KEY
            if not api_key:
                return jsonify({'respuesta': 'No tengo una llave de Gemini configurada, señor. Agreguela en Ajustes o en el archivo .env.'}), 400

        historial = cargar_memoria()

        try:
            ahora = datetime.now(ZoneInfo(zona_horaria))
        except Exception:
            ahora = datetime.now()
        fecha_hora_str = ahora.strftime('%A %d de %B de %Y, %H:%M')

        recuerdos = cargar_memoria_persistente()
        texto_recuerdos = ''
        if recuerdos:
            texto_recuerdos = ' Datos importantes que ya sabes del usuario: ' + '; '.join(recuerdos) + '.'

        system_prompt = SYSTEM_PROMPT_BASE + f' La fecha y hora ACTUAL es: {fecha_hora_str}.' + texto_recuerdos

        turnos = list(historial[-20:])  # ultimos turnos, para no saturar el contexto del modelo chico
        turnos.append({'role': 'user', 'texto': mensaje_usuario})

        if proveedor == 'groq':
            respuesta = generar_groq(system_prompt, turnos, api_key)
        else:
            respuesta = generar_gemini(system_prompt, turnos, api_key)

        if not respuesta.strip():
            respuesta = 'Parece que mis circuitos se distrajeron un instante, señor. ¿Podría repetirlo?'

        if '[CONSULTAR_BATERIA]' in respuesta:
            bateria = estado_bateria()
            respuesta = respuesta.replace('[CONSULTAR_BATERIA]', '').strip()
            if bateria:
                texto_bateria = f"{bateria['porcentaje']}%, {'cargando' if bateria['cargando'] else 'sin cargar'}"
                respuesta += f' Bateria al {texto_bateria}, señor.'
            else:
                respuesta += ' No pude leer la bateria en este momento, señor.'

        respuesta = ejecutar_acciones_dispositivo(respuesta)
        respuesta = procesar_recuerdos(respuesta)

        historial.append({'role': 'user', 'texto': mensaje_usuario})
        historial.append({'role': 'assistant', 'texto': respuesta})
        guardar_memoria(historial)

        return jsonify({'respuesta': respuesta})

    except requests.exceptions.Timeout as e:
        print('[ERROR] Timeout esperando respuesta del proveedor de IA:', e)
        traceback.print_exc()
        return jsonify({'respuesta': 'La IA esta tardando demasiado en responder, señor. Intente de nuevo en un momento.'}), 504

    except requests.exceptions.HTTPError as e:
        print('[ERROR] HTTPError del proveedor de IA:', e)
        if e.response is not None:
            print('[ERROR] Codigo:', e.response.status_code, '- Cuerpo:', e.response.text[:2000])
        traceback.print_exc()
        if e.response is not None and e.response.status_code in (400, 401, 403):
            return jsonify({'respuesta': 'La llave configurada parece invalida o sin permisos, señor. Revisela en Ajustes.'}), 401
        return jsonify({'respuesta': 'El proveedor de IA respondio con un error, señor.'}), 502

    except requests.exceptions.ConnectionError as e:
        print('[ERROR] ConnectionError hablando con el proveedor de IA:', e)
        traceback.print_exc()
        return jsonify({'respuesta': 'No logro conectarme en este momento, señor. Verifique la conexion a internet o la clave de API.'}), 500

    except Exception as e:
        print('[ERROR] Excepcion inesperada en /chat:', e)
        traceback.print_exc()
        return jsonify({'respuesta': 'Algo ha fallado de mi lado, señor.'}), 500


import logging
logging.getLogger('werkzeug').setLevel(logging.WARNING)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    print(f'Jarvis (modelo local) corriendo en http://localhost:{port}')
    app.run(host='0.0.0.0', port=port)
