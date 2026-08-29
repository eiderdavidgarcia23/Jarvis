import sys

RUTA = 'public/index.html'

with open(RUTA, 'r', encoding='utf-8') as f:
    contenido = f.read()

original = contenido

def reemplazar_unico(contenido, old, new, nombre):
    n = contenido.count(old)
    if n != 1:
        print(f'✗ ERROR en "{nombre}": se esperaba 1 aparicion, se encontraron {n}. NO se aplico ningun cambio.')
        sys.exit(1)
    return contenido.replace(old, new)

old_header_card = '''      div.innerHTML =
        '<div style="display:flex; justify-content:space-between; align-items:center;">' +
        '<span style="font-weight:bold; color:#e8feff;">Clave ' + (c.indice + 1) + '</span>' +
        (data.claves.length > 1 ? '<button onclick="eliminarClaveUso(' + c.indice + ')" style="background:transparent; border:none; color:#ff8080; font-size:11px; padding:0;">Quitar</button>' : '') +
        '</div>' +
        modelosHtml;'''

new_header_card = '''      div.innerHTML =
        '<div style="display:flex; justify-content:space-between; align-items:center;">' +
        '<span style="font-weight:bold; color:#e8feff;">Clave ' + (c.indice + 1) +
        (c.preferida ? ' <span style="font-weight:normal; font-size:10px; color:#ffd166; border:1px solid #ffd16655; border-radius:8px; padding:1px 6px; margin-left:4px;">PREFERIDA</span>' : '') +
        '</span>' +
        '<div style="display:flex; gap:8px;">' +
        (!c.preferida ? '<button onclick="preferirClaveUso(' + c.indice + ')" style="background:transparent; border:1px solid #00e5ff44; color:#00e5ff; font-size:11px; padding:3px 8px; border-radius:6px;">Usar esta</button>' : '') +
        (data.claves.length > 1 ? '<button onclick="eliminarClaveUso(' + c.indice + ')" style="background:transparent; border:none; color:#ff8080; font-size:11px; padding:0;">Quitar</button>' : '') +
        '</div>' +
        '</div>' +
        modelosHtml;'''

contenido = reemplazar_unico(contenido, old_header_card, new_header_card, "boton usar esta clave por card")

old_eliminar_fn = '''async function eliminarClaveUso(indice) {
  try {
    const res = await fetch('/api/mis_claves/' + indice, { method: 'DELETE' });
    const data = await res.json();
    if (res.ok) cargarClavesUso();
  } catch (e) {}
}'''

new_eliminar_fn = old_eliminar_fn + '''

async function preferirClaveUso(indice) {
  try {
    const res = await fetch('/api/mis_claves/' + indice + '/preferir', { method: 'POST' });
    const data = await res.json();
    if (res.ok) cargarClavesUso();
  } catch (e) {}
}'''

contenido = reemplazar_unico(contenido, old_eliminar_fn, new_eliminar_fn, "funcion preferirClaveUso")

with open(RUTA, 'w', encoding='utf-8') as f:
    f.write(contenido)

print('✓ Cambio aplicado correctamente')
print(f'Lineas: {len(original.splitlines())} -> {len(contenido.splitlines())}')
