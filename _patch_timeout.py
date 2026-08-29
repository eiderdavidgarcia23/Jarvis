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

# 1. Bajar el timeout de 60 a 35 segundos, para no quedar colgado tanto tiempo
old_timeout = '''    resp = requests.post(
        GEMINI_URL,
        headers={'x-goog-api-key': clave_gemini or GEMINI_API_KEY, 'Content-Type': 'application/json'},
        json=payload,
        timeout=60
    )'''

new_timeout = '''    resp = requests.post(
        GEMINI_URL,
        headers={'x-goog-api-key': clave_gemini or GEMINI_API_KEY, 'Content-Type': 'application/json'},
        json=payload,
        timeout=35
    )'''

contenido = reemplazar_unico(contenido, old_timeout, new_timeout, "bajar timeout a 35s")

# 2. Si una clave tarda demasiado (Timeout), probar la siguiente en vez de fallar
old_rotando = '''        except requests.exceptions.HTTPError as e:
            if es_error_limite(e):
                marcar_clave_agotada(nombre_usuario, indice, MODELO_TEXTO)
                continue
            raise'''

new_rotando = '''        except requests.exceptions.HTTPError as e:
            if es_error_limite(e):
                marcar_clave_agotada(nombre_usuario, indice, MODELO_TEXTO)
                continue
            raise
        except requests.exceptions.Timeout:
            print(f'[gemini_generar_rotando] Clave {indice} tardo demasiado, probando siguiente.')
            continue'''

contenido = reemplazar_unico(contenido, old_rotando, new_rotando, "rotar clave tambien por timeout")

with open(RUTA, 'w', encoding='utf-8') as f:
    f.write(contenido)

print('✓ Todos los cambios se aplicaron correctamente')
print(f'Lineas: {len(original.splitlines())} -> {len(contenido.splitlines())}')
