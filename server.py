import os
import re
import json
import subprocess
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from flask import Flask, request, jsonify, send_from_directory, Response

from comandos_dispositivo import encender_linterna, apagar_linterna, vibrar, estado_bateria

app = Flask(__name__, static_folder='public', static_url_path='')

# --- Modelo local (llama-server corriendo en el mismo Termux) ---
MODELO_LOCAL_URL = os.environ.get('MODELO_LOCAL_URL', 'http://localhost:8081/v1/chat/completions')

# --- Memoria simple, un solo usuario (vos), archivo local ---
MEMORIA_PATH = os.path.join(os.path.dirname(__file__), 'memoria_local.json')

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

# --- El cerebro: llama al modelo local en vez de Gemini ---
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
    'Nunca menciones estas etiquetas de forma literal en tu respuesta hablada.'
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

        historial = cargar_memoria()

        try:
            ahora = datetime.now(ZoneInfo(zona_horaria))
        except Exception:
            ahora = datetime.now()
        fecha_hora_str = ahora.strftime('%A %d de %B de %Y, %H:%M')

        system_prompt = SYSTEM_PROMPT_BASE + f' La fecha y hora ACTUAL es: {fecha_hora_str}.'

        turnos = list(historial[-20:])  # ultimos turnos, para no saturar el contexto del modelo chico
        turnos.append({'role': 'user', 'texto': mensaje_usuario})

        respuesta = generar_local(system_prompt, turnos)
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

        historial.append({'role': 'user', 'texto': mensaje_usuario})
        historial.append({'role': 'assistant', 'texto': respuesta})
        guardar_memoria(historial)

        return jsonify({'respuesta': respuesta})
    except requests.exceptions.ConnectionError:
        return jsonify({'respuesta': 'No logro conectarme con mi propio cerebro local, señor. ¿Esta corriendo el servidor del modelo?'}), 500
    except Exception as e:
        print('ERROR en /chat:', e)
        return jsonify({'respuesta': 'Algo ha fallado de mi lado, señor.'}), 500

import logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    print(f'Jarvis (modelo local) corriendo en http://localhost:{port}')
    app.run(host='0.0.0.0', port=port)
