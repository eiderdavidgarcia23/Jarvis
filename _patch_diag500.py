import sys

RUTA = 'server.py'

with open(RUTA, 'r', encoding='utf-8') as f:
    contenido = f.read()

original = contenido

def reemplazar_unico(contenido, old, new, nombre):
    n = contenido.count(old)
    if n != 1:
        print(f'✗ ERROR en "{nombre}": se esperaba 1 aparicion, se encontraron {n}. NO se aplico ningun cambio.')
        sys.exit(1)
    return contenido.replace(old, new)

# 1. Loguear el cuerpo completo cuando Gemini devuelve error, antes de raise_for_status
old_post = '''    resp = requests.post(
        GEMINI_URL,
        headers={'x-goog-api-key': clave_gemini or GEMINI_API_KEY, 'Content-Type': 'application/json'},
        json=payload,
        timeout=35
    )
    resp.raise_for_status()'''

new_post = '''    resp = requests.post(
        GEMINI_URL,
        headers={'x-goog-api-key': clave_gemini or GEMINI_API_KEY, 'Content-Type': 'application/json'},
        json=payload,
        timeout=35
    )
    if resp.status_code >= 400:
        print(f'[gemini_generar] Google respondio {resp.status_code}: {resp.text[:800]}')
    resp.raise_for_status()'''

contenido = reemplazar_unico(contenido, old_post, new_post, "loguear cuerpo completo del error de Gemini")

# 2. Tratar tambien los errores 5xx (fallas del lado de Google) como motivo
# para rotar a la siguiente clave, ademas del limite agotado
old_es_limite = '''def es_error_limite(excepcion):
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
    return False'''

new_es_limite = '''def es_error_limite(excepcion):
    resp = getattr(excepcion, 'response', None)
    if resp is None:
        return False
    if resp.status_code == 429:
        return True
    if resp.status_code >= 500:
        return True
    if resp.status_code == 400:
        try:
            cuerpo = resp.text.lower()
        except Exception:
            return False
        return 'resource_exhausted' in cuerpo or 'quota' in cuerpo
    return False'''

contenido = reemplazar_unico(contenido, old_es_limite, new_es_limite, "rotar tambien ante errores 5xx de Google")

with open(RUTA, 'w', encoding='utf-8') as f:
    f.write(contenido)

print('✓ Todos los cambios se aplicaron correctamente')
print(f'Lineas: {len(original.splitlines())} -> {len(contenido.splitlines())}')
