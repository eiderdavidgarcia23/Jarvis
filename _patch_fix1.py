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

def reemplazar_todos(contenido, old, new, nombre, esperados):
    n = contenido.count(old)
    if n != esperados:
        print(f'✗ ERROR en "{nombre}": se esperaban {esperados} apariciones, se encontraron {n}. NO se aplico ningun cambio.')
        sys.exit(1)
    return contenido.replace(old, new)

# 1. FIX del crash: usar nombre_cuenta (no usuario_invitado) al registrar uso
contenido = reemplazar_unico(
    contenido,
    "        respuesta = gemini_generar_rotando(system_prompt, turnos, imagen_base64 if imagen_base64 else None, nombre_usuario=usuario_invitado, claves_cifradas=claves_gemini_invitado)",
    "        respuesta = gemini_generar_rotando(system_prompt, turnos, imagen_base64 if imagen_base64 else None, nombre_usuario=nombre_cuenta, claves_cifradas=claves_gemini_invitado)",
    "fix llamada principal a Gemini"
)

contenido = reemplazar_todos(
    contenido,
    "            respuesta = gemini_generar_rotando(system_prompt, turnos, nombre_usuario=usuario_invitado, claves_cifradas=claves_gemini_invitado)",
    "            respuesta = gemini_generar_rotando(system_prompt, turnos, nombre_usuario=nombre_cuenta, claves_cifradas=claves_gemini_invitado)",
    "fix llamadas de seguimiento (tareas/busqueda)",
    esperados=2
)

# 2. Mostrar en consola el motivo real cuando Google rechaza una clave
old_funciona = '''def clave_gemini_funciona(clave):
    try:
        resp = requests.post(
            GEMINI_URL,
            headers={'x-goog-api-key': clave, 'Content-Type': 'application/json'},
            json={'model': MODELO_TEXTO, 'input': [{'type': 'user_input', 'content': [{'type': 'text', 'text': 'hola'}]}]},
            timeout=20
        )
        return resp.status_code == 200
    except Exception:
        return False'''

new_funciona = '''def clave_gemini_funciona(clave):
    try:
        resp = requests.post(
            GEMINI_URL,
            headers={'x-goog-api-key': clave, 'Content-Type': 'application/json'},
            json={'model': MODELO_TEXTO, 'input': [{'type': 'user_input', 'content': [{'type': 'text', 'text': 'hola'}]}]},
            timeout=20
        )
        if resp.status_code != 200:
            print(f'[validacion clave Gemini] Google respondio {resp.status_code}: {resp.text[:300]}')
        return resp.status_code == 200
    except Exception as e:
        print(f'[validacion clave Gemini] Excepcion: {e}')
        return False'''

contenido = reemplazar_unico(contenido, old_funciona, new_funciona, "log del motivo real de rechazo")

with open(RUTA, 'w', encoding='utf-8') as f:
    f.write(contenido)

print('✓ Todos los cambios se aplicaron correctamente')
print(f'Lineas: {len(original.splitlines())} -> {len(contenido.splitlines())}')
