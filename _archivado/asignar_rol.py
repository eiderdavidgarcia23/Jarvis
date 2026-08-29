"""
Asigna el rol 'administrador' o 'usuario' a un invitado ya registrado.
Uso: python asignar_rol.py <nombre_usuario> <administrador|usuario>
"""
import sys
from almacenamiento_firebase import cargar_usuario, guardar_usuario

def main():
    if len(sys.argv) != 3:
        print("Uso: python asignar_rol.py <nombre_usuario> <administrador|usuario>")
        sys.exit(1)

    nombre = sys.argv[1].strip().lower()
    rol = sys.argv[2].strip()

    if rol not in ('administrador', 'usuario'):
        print("El rol debe ser 'administrador' o 'usuario'.")
        sys.exit(1)

    datos = cargar_usuario(nombre)
    if not datos:
        print(f"No existe el usuario '{nombre}'.")
        sys.exit(1)

    datos['rol'] = rol
    guardar_usuario(nombre, datos)
    print(f"Listo: '{nombre}' ahora tiene el rol '{rol}'.")

if __name__ == '__main__':
    main()
