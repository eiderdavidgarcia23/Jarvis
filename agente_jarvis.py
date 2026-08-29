import requests

JARVIS_URL = 'http://127.0.0.1:8081/v1/chat/completions'

def preguntar_jarvis(mensaje, historial=None):
    """Le pregunta al modelo local (Qwen corriendo con llama-server).
    historial: lista opcional [{"role": "user"|"assistant", "content": "..."}]"""
    mensajes = list(historial) if historial else []
    mensajes.append({'role': 'user', 'content': mensaje})
    try:
        respuesta = requests.post(
            JARVIS_URL,
            json={'messages': mensajes, 'temperature': 0.7},
            timeout=30
        )
        respuesta.raise_for_status()
        data = respuesta.json()
        return data['choices'][0]['message']['content'].strip()
    except requests.exceptions.ConnectionError:
        return 'Señor, no logro conectarme con mi núcleo local en este momento.'
    except Exception as e:
        print('[preguntar_jarvis] Error:', e)
        return 'Tuve un problema procesando eso, señor.'
