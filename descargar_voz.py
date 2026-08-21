import os
import urllib.request

VOZ_DIR = 'voz_render'
VOZ_ONNX = os.path.join(VOZ_DIR, 'es_ES-davefx-medium.onnx')
VOZ_JSON = os.path.join(VOZ_DIR, 'es_ES-davefx-medium.onnx.json')

BASE_URL = 'https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium/'

os.makedirs(VOZ_DIR, exist_ok=True)

if not os.path.exists(VOZ_ONNX):
    print('Descargando modelo de voz...')
    urllib.request.urlretrieve(BASE_URL + 'es_ES-davefx-medium.onnx', VOZ_ONNX)

if not os.path.exists(VOZ_JSON):
    urllib.request.urlretrieve(BASE_URL + 'es_ES-davefx-medium.onnx.json', VOZ_JSON)

print('Voz lista.')
