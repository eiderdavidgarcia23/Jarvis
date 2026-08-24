"""
Módulo de estado de COOPMOCUR para Jarvis.
Lee directo de la misma base de Firebase que usa COOPMOCUR
(coopmocur-default-rtdb), vía API REST simple con requests,
igual que hace almacenamiento_firebase.py con los datos de Jarvis.
"""

import requests

FIREBASE_BASE_URL = "https://coopmocur-default-rtdb.firebaseio.com"

# Umbral por defecto para considerar "stock bajo" (ajustable)
UMBRAL_STOCK_BAJO = 5

# Cuántas entradas de historial traer como "recientes"
HISTORIAL_RECIENTE_N = 10


def _get(coleccion):
    """Trae una colección completa de Firebase. Devuelve {} si está vacía o falla."""
    url = f"{FIREBASE_BASE_URL}/{coleccion}.json"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        datos = resp.json()
        return datos or {}
    except Exception as e:
        print(f"[estado_coopmocur] Error obteniendo '{coleccion}': {e}")
        return {}


def obtener_repuestos():
    """Devuelve el diccionario completo de repuestos {id: {...}}."""
    return _get("repuestos")


def obtener_historial():
    """Devuelve el diccionario completo de historial {id: {...}}."""
    return _get("historial")


def obtener_usuarios():
    """Devuelve el diccionario completo de usuarios {id: {...}}."""
    return _get("usuarios")


def obtener_conductores():
    """Devuelve el diccionario completo de conductores {id: {...}}."""
    return _get("conductores")


def _repuestos_stock_bajo(repuestos, umbral=UMBRAL_STOCK_BAJO):
    """Filtra repuestos con cantidad disponible <= umbral."""
    bajos = []
    for rid, r in repuestos.items():
        try:
            cantidad = int(r.get("cantidad", 0))
        except (TypeError, ValueError):
            cantidad = 0
        if cantidad <= umbral:
            bajos.append({
                "id": rid,
                "nombre": r.get("nombre", "Sin nombre"),
                "cantidad": cantidad
            })
    # Los más críticos primero
    bajos.sort(key=lambda x: x["cantidad"])
    return bajos


def _historial_reciente(historial, n=HISTORIAL_RECIENTE_N):
    """Devuelve las n entradas más recientes del historial, si tienen campo 'fecha'."""
    entradas = []
    for hid, h in historial.items():
        entradas.append({"id": hid, **h})
    # Ordena por fecha si existe el campo, si no deja el orden que venga
    entradas.sort(key=lambda x: x.get("fecha", ""), reverse=True)
    return entradas[:n]


def generar_resumen_coopmocur():
    """
    Arma un resumen completo del estado de COOPMOCUR:
    stock, alertas de stock bajo, historial reciente, usuarios y conductores.
    Este es el diccionario que se expone en /api/estado_coopmocur
    y el que se le pasa a Gemini cuando preguntan por el chat.
    """
    repuestos = obtener_repuestos()
    historial = obtener_historial()
    usuarios = obtener_usuarios()
    conductores = obtener_conductores()

    stock_bajo = _repuestos_stock_bajo(repuestos)
    reciente = _historial_reciente(historial)

    return {
        "inventario": {
            "total_repuestos": len(repuestos),
            "stock_bajo": stock_bajo,
            "cantidad_alertas": len(stock_bajo)
        },
        "actividad": {
            "total_movimientos_historial": len(historial),
            "movimientos_recientes": reciente
        },
        "usuarios": {
            "total_usuarios": len(usuarios)
        },
        "conductores": {
            "total_conductores": len(conductores)
        },
        "conectado": True if (repuestos or historial or usuarios) else False
    }


if __name__ == "__main__":
    import json
    print(json.dumps(generar_resumen_coopmocur(), indent=2, ensure_ascii=False))
