"""
Comandos directos al hardware del celular via Termux:API.
No pasan por ningun modelo de IA para ejecutarse - el modelo solo decide
CUANDO usarlos (emitiendo una etiqueta), la ejecucion real es este codigo.
"""

import subprocess
import json


def _correr(comando, timeout=10):
    try:
        resultado = subprocess.run(
            comando, capture_output=True, text=True, timeout=timeout
        )
        return resultado.returncode == 0, resultado.stdout.strip()
    except Exception as e:
        return False, str(e)


def encender_linterna():
    ok, _ = _correr(['termux-torch', 'on'])
    return ok


def apagar_linterna():
    ok, _ = _correr(['termux-torch', 'off'])
    return ok


def vibrar(duracion_ms=500):
    ok, _ = _correr(['termux-vibrate', '-d', str(duracion_ms)])
    return ok


def estado_bateria():
    """Devuelve un dict simple con el porcentaje y si esta cargando, o None si falla."""
    ok, salida = _correr(['termux-battery-status'])
    if not ok:
        return None
    try:
        data = json.loads(salida)
        return {
            'porcentaje': data.get('percentage'),
            'cargando': data.get('status') == 'CHARGING',
            'estado': data.get('status')
        }
    except Exception:
        return None
