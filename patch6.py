with open('server.py', 'r', encoding='utf-8') as f:
    contenido = f.read()

vieja = "        mensaje_usuario = data.get('mensaje', '')"
nueva = (
    "        mensaje_usuario = data.get('mensaje', '')\n"
    "        ubicacion_usuario = data.get('ubicacion', '')"
)
if vieja in contenido and "ubicacion_usuario" not in contenido.split(vieja)[0]:
    contenido = contenido.replace(vieja, nueva, 1)

# Inyectar la ubicacion en el system prompt, justo despues de la fecha/hora
vieja2 = "'Usa siempre este dato exacto si te preguntan la hora o la fecha, '\n                    'nunca inventes ni calcules una hora distinta.'"
if vieja2 in contenido:
    nueva2 = vieja2[:-1] + (
        " Ademas, la ubicacion actual del usuario es: {ubicacion}. Usa esta ubicacion "
        "SIEMPRE que necesites buscar clima, noticias locales u otra informacion que "
        "dependa de donde esta el usuario, sin preguntarle donde esta.'"
    )
    contenido = contenido.replace(vieja2, nueva2)

    # Convertir el f-string para que incluya la variable ubicacion
    vieja3 = "                    f'La fecha y hora ACTUAL y REAL es: {fecha_hora_str}. '"
    nueva3 = (
        "                    f'La fecha y hora ACTUAL y REAL es: {fecha_hora_str}. '\n"
    )
    # Aseguramos que el .format(ubicacion=...) se aplique al final del content
    if "content': (" in contenido:
        contenido = contenido.replace(
            "'rompes el personaje. '",
            "'rompes el personaje. '"
        )

with open('server.py', 'w', encoding='utf-8') as f:
    f.write(contenido)

print("Revisar manualmente - ver instrucciones siguientes")
