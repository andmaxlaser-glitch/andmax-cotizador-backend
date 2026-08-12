import ezdxf

def procesar_archivo_dxf(ruta_archivo):
    print(">>> ALERTA: ESTOY USANDO EL ARCHIVO NUEVO Y LIMPIO <<<")
    doc = ezdxf.readfile(ruta_archivo)
    msp = doc.modelspace()
    
    # Contemos cuántas entidades CIRCLE hay realmente
    circulos = len(msp.query('CIRCLE'))
    lineas = len(msp.query('LINE'))
    polilineas = len(msp.query('LWPOLYLINE'))
    
    return {
        "tipo": "PRUEBA_LIMPIA",
        "circulos_nativos": circulos,
        "lineas": lineas,
        "polilineas": polilineas
    }
