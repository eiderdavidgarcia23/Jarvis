import os
import re
import requests

FIREBASE_DB_URL = os.environ.get('FIREBASE_DB_URL', 'https://coopmocur-default-rtdb.firebaseio.com')

def _fb_url(ruta):
    return f'{FIREBASE_DB_URL}/{ruta}.json'

def id_seguro(usuario_id):
    return re.sub(r'[^a-zA-Z0-9_-]', '', usuario_id or 'anonimo')[:64] or 'anonimo'

def cargar_usuario(nombre):
    resp = requests.get(_fb_url(f'jarvis_usuarios/{nombre.lower()}'), timeout=10)
    resp.raise_for_status()
    return resp.json()

def guardar_usuario(nombre, datos):
    resp = requests.put(_fb_url(f'jarvis_usuarios/{nombre.lower()}'), json=datos, timeout=10)
    resp.raise_for_status()

def cargar_memoria(usuario_id):
    resp = requests.get(_fb_url(f'jarvis_memoria/{id_seguro(usuario_id)}'), timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data if data else []

def guardar_memoria(usuario_id, historial):
    resp = requests.put(_fb_url(f'jarvis_memoria/{id_seguro(usuario_id)}'), json=historial, timeout=10)
    resp.raise_for_status()

def cargar_recordatorios(usuario_id):
    resp = requests.get(_fb_url(f'jarvis_recordatorios/{id_seguro(usuario_id)}'), timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data if data else []

def guardar_recordatorios(usuario_id, lista):
    resp = requests.put(_fb_url(f'jarvis_recordatorios/{id_seguro(usuario_id)}'), json=lista, timeout=10)
    resp.raise_for_status()

def cargar_preferencias(usuario_id):
    resp = requests.get(_fb_url(f'jarvis_preferencias/{id_seguro(usuario_id)}'), timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data if data else {}

def guardar_preferencias(usuario_id, prefs):
    resp = requests.put(_fb_url(f'jarvis_preferencias/{id_seguro(usuario_id)}'), json=prefs, timeout=10)
    resp.raise_for_status()
