PALABRAS_BUSQUEDA = [
    'busca', 'búsca', 'buscá', 'buscar', 'última noticia', 'últimas noticias',
    'qué pasó con', 'que paso con', 'quién es', 'quien es', 'qué es', 'que es',
    'cuánto cuesta', 'cuanto cuesta', 'cotización', 'cotizacion', 'clima',
    'resultado de', 'cuándo es', 'cuando es', 'precio de', 'noticias de'
]

FRASES_CONFIRMACION = ['si', 'sí', 'dale', 'procede', 'procedé', 'ok', 'okay', 'claro', 'adelante']
FRASES_CANCELACION = ['no', 'cancela', 'cancelar', 'olvidalo', 'olvídalo', 'déjalo', 'dejalo']

def necesita_busqueda(mensaje):
    mensaje_low = (mensaje or '').lower()
    return any(palabra in mensaje_low for palabra in PALABRAS_BUSQUEDA)

def es_confirmacion(mensaje):
    return (mensaje or '').strip().lower() in FRASES_CONFIRMACION

def es_cancelacion(mensaje):
    return (mensaje or '').strip().lower() in FRASES_CANCELACION
