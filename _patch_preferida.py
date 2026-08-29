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

# 1. gemini_generar_rotando acepta un indice preferido para empezar por ahi
old_rotando_def = "def gemini_generar_rotando(system_prompt, turnos, imagen_base64=None, nombre_usuario=None, claves_cifradas=None):"
new_rotando_def = "def gemini_generar_rotando(system_prompt, turnos, imagen_base64=None, nombre_usuario=None, claves_cifradas=None, indice_preferido=None):"
contenido = reemplazar_unico(contenido, old_rotando_def, new_rotando_def, "parametro indice_preferido")

old_for = '''    for indice, clave_cifrada in enumerate(claves_cifradas):
        clave = None'''
new_for = '''    orden_indices = list(range(len(claves_cifradas)))
    if isinstance(indice_preferido, int) and 0 <= indice_preferido < len(claves_cifradas):
        orden_indices = [indice_preferido] + [i for i in orden_indices if i != indice_preferido]

    for indice in orden_indices:
        clave_cifrada = claves_cifradas[indice]
        clave = None'''
contenido = reemplazar_unico(contenido, old_for, new_for, "recorrer claves en el orden preferido")

# 2. /chat: cargar la preferencia guardada y pasarla a las 3 llamadas
old_chat = '''        claves_gemini_invitado = []
        nombre_cuenta = 'david' if es_dueno else usuario_invitado
        if nombre_cuenta:
            datos_usuario = cargar_usuario(nombre_cuenta)
            claves_gemini_invitado = obtener_claves_gemini(datos_usuario)
        if usuario_invitado:'''
new_chat = '''        claves_gemini_invitado = []
        indice_preferido = None
        nombre_cuenta = 'david' if es_dueno else usuario_invitado
        if nombre_cuenta:
            datos_usuario = cargar_usuario(nombre_cuenta)
            claves_gemini_invitado = obtener_claves_gemini(datos_usuario)
            if datos_usuario:
                indice_preferido = datos_usuario.get('clave_preferida_indice')
        if usuario_invitado:'''
contenido = reemplazar_unico(contenido, old_chat, new_chat, "cargar clave preferida en /chat")

contenido = reemplazar_unico(
    contenido,
    "        respuesta = gemini_generar_rotando(system_prompt, turnos, imagen_base64 if imagen_base64 else None, nombre_usuario=nombre_cuenta, claves_cifradas=claves_gemini_invitado)",
    "        respuesta = gemini_generar_rotando(system_prompt, turnos, imagen_base64 if imagen_base64 else None, nombre_usuario=nombre_cuenta, claves_cifradas=claves_gemini_invitado, indice_preferido=indice_preferido)",
    "pasar preferencia a la llamada principal"
)
contenido = reemplazar_todos(
    contenido,
    "            respuesta = gemini_generar_rotando(system_prompt, turnos, nombre_usuario=nombre_cuenta, claves_cifradas=claves_gemini_invitado)",
    "            respuesta = gemini_generar_rotando(system_prompt, turnos, nombre_usuario=nombre_cuenta, claves_cifradas=claves_gemini_invitado, indice_preferido=indice_preferido)",
    "pasar preferencia a llamadas de seguimiento",
    esperados=2
)

# 3. Nueva ruta para elegir la clave preferida
old_delete = '''@app.route('/api/mis_claves/<int:indice>', methods=['DELETE'])
def api_eliminar_clave(indice):'''
new_delete = '''@app.route('/api/mis_claves/<int:indice>/preferir', methods=['POST'])
def api_preferir_clave(indice):
    nombre = nombre_cuenta_actual()
    if not nombre:
        return jsonify({'error': 'no autorizado'}), 403
    datos_usuario = cargar_usuario(nombre) or {}
    claves = obtener_claves_gemini(datos_usuario)
    if indice < 0 or indice >= len(claves):
        return jsonify({'error': 'indice invalido'}), 400
    datos_usuario['clave_preferida_indice'] = indice
    guardar_usuario(nombre, datos_usuario)
    return jsonify({'ok': True})

@app.route('/api/mis_claves/<int:indice>', methods=['DELETE'])
def api_eliminar_clave(indice):'''
contenido = reemplazar_unico(contenido, old_delete, new_delete, "ruta para marcar clave preferida")

# 4. GET /api/mis_claves: marcar 'activo' respetando el orden de preferencia,
# y devolver cual es la preferida
old_get = '''@app.route('/api/mis_claves', methods=['GET'])
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

new_get = '''@app.route('/api/mis_claves', methods=['GET'])
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

    preferida = datos_usuario.get('clave_preferida_indice')
    if not (isinstance(preferida, int) and 0 <= preferida < len(claves)):
        preferida = None
    orden_indices = list(range(len(claves)))
    if preferida is not None:
        orden_indices = [preferida] + [i for i in orden_indices if i != preferida]

    def esta_agotado(i, modelo):
        entrada = (uso.get(str(i)) or {}).get(modelo) or {}
        return bool(entrada.get('agotada')) if entrada.get('fecha') == hoy else False

    activo_actual = None
    for i in orden_indices:
        for modelo_info in MODELOS_DISPONIBLES:
            if not esta_agotado(i, modelo_info['id']):
                activo_actual = (i, modelo_info['id'])
                break
        if activo_actual:
            break

    resultado = []
    for i in range(len(claves)):
        modelos_resultado = []
        for modelo_info in MODELOS_DISPONIBLES:
            modelo = modelo_info['id']
            entrada = (uso.get(str(i)) or {}).get(modelo) or {}
            vigente = entrada.get('fecha') == hoy
            agotada = bool(entrada.get('agotada')) if vigente else False
            modelos_resultado.append({
                'id': modelo,
                'usados_hoy': entrada.get('usados', 0) if vigente else 0,
                'agotada_hoy': agotada,
                'activo': activo_actual == (i, modelo),
                'referencia_aprox': modelo_info['referencia_aprox']
            })
        resultado.append({'indice': i, 'preferida': (i == preferida), 'modelos': modelos_resultado})
    return jsonify({'claves': resultado, 'segundos_para_reset': segundos_para_reset})'''

contenido = reemplazar_unico(contenido, old_get, new_get, "reportar orden de preferencia en /api/mis_claves")

with open(RUTA, 'w', encoding='utf-8') as f:
    f.write(contenido)

print('✓ Todos los cambios se aplicaron correctamente')
print(f'Lineas: {len(original.splitlines())} -> {len(contenido.splitlines())}')
