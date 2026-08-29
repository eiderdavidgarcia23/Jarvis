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

old_carga = '''async function cargarClavesUso() {
  const cont = document.getElementById('listaClavesUso');
  cont.innerHTML = '<p style="font-size:12px; color:#00e5ff99;">Cargando...</p>';
  try {
    const res = await fetch('/api/mis_claves');
    const data = await res.json();
    if (!res.ok) { cont.innerHTML = '<p style="font-size:12px; color:#ff8080;">' + (data.error || 'Error al cargar') + '</p>'; return; }
    cont.innerHTML = '';
    const restablece = formatearTiempoRestante(data.segundos_para_reset || 0);
    data.claves.forEach((c) => {
      const referencia = c.referencia_aprox || 1000;
      const pct = Math.min(100, Math.round((c.usados_hoy / referencia) * 100));
      const div = document.createElement('div');
      div.className = 'clave-uso-item' + (c.agotada_hoy ? ' clave-uso-agotada' : '');
      div.innerHTML =
        '<div style="display:flex; justify-content:space-between; align-items:flex-start;">' +
        '<div>' +
        '<div style="font-weight:bold; color:#e8feff;">Clave ' + (c.indice + 1) +
        (c.activa ? ' <span style="font-weight:normal; font-size:10px; color:#00e5ff; border:1px solid #00e5ff55; border-radius:8px; padding:1px 6px; margin-left:4px;">\u25cf ACTIVA</span>' : '') +
        (c.agotada_hoy ? ' <span style="font-weight:normal; font-size:10px; color:#ff8080; border:1px solid #ff505055; border-radius:8px; padding:1px 6px; margin-left:4px;">AGOTADA</span>' : '') +
        '</div>' +
        '<div style="font-size:11px; color:#00e5ff77; margin-top:2px;">' + c.modelo + ' \u00b7 se restablece en ' + restablece + '</div>' +
        '</div>' +
        '<div style="text-align:right;">' +
        '<div style="font-weight:bold; font-size:16px; color:#e8feff;">' + c.usados_hoy + '</div>' +
        '<div style="font-size:10px; color:#00e5ff77;">usados hoy</div>' +
        (data.claves.length > 1 ? '<button onclick="eliminarClaveUso(' + c.indice + ')" style="background:transparent; border:none; color:#ff8080; font-size:11px; margin-top:4px; padding:0;">Quitar</button>' : '') +
        '</div>' +
        '</div>' +
        '<div class="clave-uso-barra-fondo"><div class="clave-uso-barra" style="width:' + pct + '%"></div></div>' +
        '<div style="text-align:right; font-size:10px; color:#00e5ff66; margin-top:4px;">~' + pct + '% de la referencia aprox. (' + referencia + ')</div>';
      cont.appendChild(div);
    });
  } catch (e) {
    cont.innerHTML = '<p style="font-size:12px; color:#ff8080;">Error de conexion.</p>';
  }
}'''

new_carga = '''async function cargarClavesUso() {
  const cont = document.getElementById('listaClavesUso');
  cont.innerHTML = '<p style="font-size:12px; color:#00e5ff99;">Cargando...</p>';
  try {
    const res = await fetch('/api/mis_claves');
    const data = await res.json();
    if (!res.ok) { cont.innerHTML = '<p style="font-size:12px; color:#ff8080;">' + (data.error || 'Error al cargar') + '</p>'; return; }
    cont.innerHTML = '';
    const restablece = formatearTiempoRestante(data.segundos_para_reset || 0);
    data.claves.forEach((c) => {
      const div = document.createElement('div');
      div.className = 'clave-uso-item';
      let modelosHtml = '';
      c.modelos.forEach((m) => {
        const pct = Math.min(100, Math.round((m.usados_hoy / m.referencia_aprox) * 100));
        const colorBarra = m.agotada_hoy ? '#ff5050' : '#00e5ff';
        modelosHtml +=
          '<div style="margin-top:10px; padding-top:10px; border-top:1px solid #00e5ff1a;">' +
          '<div style="display:flex; justify-content:space-between; align-items:flex-start;">' +
          '<div>' +
          '<div style="font-size:12px; color:#e8feff;">' + m.id +
          (m.activo ? ' <span style="font-size:10px; color:#00e5ff; border:1px solid #00e5ff55; border-radius:8px; padding:1px 6px; margin-left:4px;">\u25cf ACTIVO</span>' : '') +
          (m.agotada_hoy ? ' <span style="font-size:10px; color:#ff8080; border:1px solid #ff505055; border-radius:8px; padding:1px 6px; margin-left:4px;">AGOTADO</span>' : '') +
          '</div>' +
          '<div style="font-size:10px; color:#00e5ff77; margin-top:2px;">se restablece en ' + restablece + '</div>' +
          '</div>' +
          '<div style="text-align:right;">' +
          '<div style="font-weight:bold; font-size:15px; color:#e8feff;">' + m.usados_hoy + '</div>' +
          '<div style="font-size:10px; color:#00e5ff77;">usados hoy</div>' +
          '</div>' +
          '</div>' +
          '<div class="clave-uso-barra-fondo"><div class="clave-uso-barra" style="width:' + pct + '%; background:' + colorBarra + '"></div></div>' +
          '<div style="text-align:right; font-size:10px; color:#00e5ff66; margin-top:4px;">~' + pct + '% de la referencia aprox. (' + m.referencia_aprox + ')</div>' +
          '</div>';
      });
      div.innerHTML =
        '<div style="display:flex; justify-content:space-between; align-items:center;">' +
        '<span style="font-weight:bold; color:#e8feff;">Clave ' + (c.indice + 1) + '</span>' +
        (data.claves.length > 1 ? '<button onclick="eliminarClaveUso(' + c.indice + ')" style="background:transparent; border:none; color:#ff8080; font-size:11px; padding:0;">Quitar</button>' : '') +
        '</div>' +
        modelosHtml;
      cont.appendChild(div);
    });
  } catch (e) {
    cont.innerHTML = '<p style="font-size:12px; color:#ff8080;">Error de conexion.</p>';
  }
}'''

contenido = reemplazar_unico(contenido, old_carga, new_carga, "mostrar cada modelo por clave en el panel de Uso")

with open(RUTA, 'w', encoding='utf-8') as f:
    f.write(contenido)

print('✓ Cambio aplicado correctamente')
print(f'Lineas: {len(original.splitlines())} -> {len(contenido.splitlines())}')
