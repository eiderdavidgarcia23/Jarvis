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

# 1. Agregar la lista de modelos disponibles
old_modelos = """MODELO_TEXTO = 'gemini-3.7-flash'
MODELO_VISION = 'gemini-3.7-flash'"""

new_modelos = """MODELO_TEXTO = 'gemini-3.7-flash'
MODELO_VISION = 'gemini-3.7-flash'

# Modelos que Jarvis prueba en orden por cada clave: primero el de mejor
# calidad; si Google reporta el limite diario agotado para ese modelo,
# prueba el siguiente (mas limitado en capacidad pero con cupo diario mucho
# mayor) antes de pasar a la siguiente clave del usuario.
MODELOS_DISPONIBLES = [
    {'id': 'gemini-3.7-flash', 'referencia_aprox': 20},
    {'id': 'gemini-3.1-flash-lite', 'referencia_aprox': 1000},
]"""

contenido = reemplazar_unico(contenido, old_modelos, new_modelos, "lista de modelos disponibles")

# 2. gemini_generar acepta el modelo como parametro
old_def = "def gemini_generar(system_prompt, turnos, imagen_base64=None, clave_gemini=None):"
new_def = "def gemini_generar(system_prompt, turnos, imagen_base64=None, clave_gemini=None, modelo=None):"
contenido = reemplazar_unico(contenido, old_def, new_def, "parametro modelo en gemini_generar")

old_payload = "    payload = {\n        'model': MODELO_TEXTO,"
new_payload = "    payload = {\n        'model': modelo or MODELO_TEXTO,"
contenido = reemplazar_unico(contenido, old_payload, new_payload, "usar el modelo pedido en el payload")

# 3. gemini_generar_rotando prueba los modelos de cada clave en orden
old_rotando = '''def gemini_generar_rotando(system_prompt, turnos, imagen_base64=None, nombre_usuario=None, claves_cifradas=None):
    """Como gemini_generar, pero si la clave activa del usuario tiene el limite
    diario agotado, prueba automaticamente con la siguiente clave guardada."""
    if not claves_cifradas:
        return gemini_generar(system_prompt, turnos, imagen_base64)

    for indice, clave_cifrada in enumerate(claves_cifradas):
        if clave_marcada_agotada_hoy(nombre_usuario, indice, MODELO_TEXTO):
            continue
        try:
            clave = descifrar(clave_cifrada)
            respuesta = gemini_generar(system_prompt, turnos, imagen_base64, clave_gemini=clave)
            registrar_uso_clave(nombre_usuario, indice, MODELO_TEXTO)
            return respuesta
        except requests.exceptions.HTTPError as e:
            if es_error_limite(e):
                marcar_clave_agotada(nombre_usuario, indice, MODELO_TEXTO)
                continue
            raise
        except requests.exceptions.Timeout:
            print(f'[gemini_generar_rotando] Clave {indice} tardo demasiado, probando siguiente.')
            continue

    return (
        'Me temo que todas sus claves de Gemini alcanzaron su limite diario, señor. '
        'Se restableceran en unas horas, o puede agregar una clave adicional desde el panel de Uso.'
    )'''

new_rotando = '''def gemini_generar_rotando(system_prompt, turnos, imagen_base64=None, nombre_usuario=None, claves_cifradas=None):
    """Prueba en orden los modelos disponibles de cada clave (mejor calidad
    primero, mas cupo diario despues); si se agotan todos los modelos de una
    clave, pasa a la siguiente clave guardada del usuario."""
    if not claves_cifradas:
        return gemini_generar(system_prompt, turnos, imagen_base64)

    for indice, clave_cifrada in enumerate(claves_cifradas):
        clave = None
        for modelo_info in MODELOS_DISPONIBLES:
            modelo = modelo_info['id']
            if clave_marcada_agotada_hoy(nombre_usuario, indice, modelo):
                continue
            try:
                if clave is None:
                    clave = descifrar(clave_cifrada)
                respuesta = gemini_generar(system_prompt, turnos, imagen_base64, clave_gemini=clave, modelo=modelo)
                registrar_uso_clave(nombre_usuario, indice, modelo)
                return respuesta
            except requests.exceptions.HTTPError as e:
                if es_error_limite(e):
                    marcar_clave_agotada(nombre_usuario, indice, modelo)
                    continue
                raise
            except requests.exceptions.Timeout:
                print(f'[gemini_generar_rotando] Clave {indice} modelo {modelo} tardo demasiado, probando siguiente.')
                continue

    return (
        'Me temo que todas sus claves de Gemini alcanzaron su limite diario, señor. '
        'Se restableceran en unas horas, o puede agregar una clave adicional desde el panel de Uso.'
    )'''

contenido = reemplazar_unico(contenido, old_rotando, new_rotando, "rotacion por modelo dentro de cada clave")

# 4. /api/mis_claves ahora reporta uso por cada modelo de cada clave
old_ruta = '''@app.route('/api/mis_claves', methods=['GET'])
def api_mis_claves():
    nombre = nombre_cuenta_actual()
    if not nombre:
        return jsonify({'error': 'no autorizado'}), 403
    datos_usuario = cargar_usuario(nombre) or {}
    claves = obtener_claves_gemini(datos_usuario)
    uso = cargar_uso_ia(nombre)
    hoy = fecha_hoy_str()
    REFERENCIA_APROX = 1000
    ahora = datetime.now()
    manana = (ahora + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    segundos_para_reset = int((manana - ahora).total_seconds())
    ya_hay_activa = False
    resultado = []
    for i in range(len(claves)):
        entrada = (uso.get(str(i)) or {}).get(MODELO_TEXTO) or {}
        vigente = entrada.get('fecha') == hoy
        agotada = bool(entrada.get('agotada')) if vigente else False
        es_activa = (not agotada) and (not ya_hay_activa)
        if es_activa:
            ya_hay_activa = True
        resultado.append({
            'indice': i,
            'modelo': MODELO_TEXTO,
            'usados_hoy': entrada.get('usados', 0) if vigente else 0,
            'agotada_hoy': agotada,
            'activa': es_activa,
            'referencia_aprox': REFERENCIA_APROX
        })
    return jsonify({'claves': resultado, 'segundos_para_reset': segundos_para_reset})'''

new_ruta = '''@app.route('/api/mis_claves', methods=['GET'])
def api_mis_claves():
    nombre = nombre_cuenta_actual()
    if not nombre:
        return jsonify({'error': 'no autorizado'}), 403
    datos_usuario = cargar_usuario(nombre) or {}
    claves = obtener_claves_gemini(datos_usuario)
    uso = cargar_uso_ia(nombre)
    hoy = fecha_hoy_str()
    ahora = datetime.now()
    manana = (ahora + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    segundos_para_reset = int((manana - ahora).total_seconds())
    ya_hay_activo = False
    resultado = []
    for i in range(len(claves)):
        modelos_resultado = []
        for modelo_info in MODELOS_DISPONIBLES:
            modelo = modelo_info['id']
            entrada = (uso.get(str(i)) or {}).get(modelo) or {}
            vigente = entrada.get('fecha') == hoy
            agotada = bool(entrada.get('agotada')) if vigente else False
            es_activo = (not agotada) and (not ya_hay_activo)
            if es_activo:
                ya_hay_activo = True
            modelos_resultado.append({
                'id': modelo,
                'usados_hoy': entrada.get('usados', 0) if vigente else 0,
                'agotada_hoy': agotada,
                'activo': es_activo,
                'referencia_aprox': modelo_info['referencia_aprox']
            })
        resultado.append({'indice': i, 'modelos': modelos_resultado})
    return jsonify({'claves': resultado, 'segundos_para_reset': segundos_para_reset})'''

contenido = reemplazar_unico(contenido, old_ruta, new_ruta, "reportar uso por modelo en /api/mis_claves")

with open(RUTA, 'w', encoding='utf-8') as f:
    f.write(contenido)

print('✓ Todos los cambios se aplicaron correctamente')
print(f'Lineas: {len(original.splitlines())} -> {len(contenido.splitlines())}')
