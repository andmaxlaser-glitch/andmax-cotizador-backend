import math
import ezdxf

def detectar_circulo_por_segmentos(lineas, tolerancia=0.01):
    """
    Analiza una lista de segmentos de línea para detectar si forman un círculo
    y extrae su centro y radio aproximado.
    """
    if not lineas:
        return None
    
    puntos = []
    for l in lineas:
        puntos.append((l['x1'], l['y1']))
        puntos.append((l['x2'], l['y2']))
        
    n = len(puntos)
    centro_x = sum(p[0] for p in puntos) / n
    centro_y = sum(p[1] for p in puntos) / n
    
    radios = [math.hypot(p[0] - centro_x, p[1] - centro_y) for p in puntos]
    radio_promedio = sum(radios) / n
    
    desviacion = math.sqrt(sum((r - radio_promedio) ** 2 for r in radios) / n)
    
    if desviacion <= tolerancia:
        perimetro_estimado = 2 * math.pi * radio_promedio
        area_estimada = math.pi * (radio_promedio ** 2)
        return {
            "tipo": "CIRCULO_DETECTADO",
            "centro": (centro_x, centro_y),
            "radio": radio_promedio,
            "perimetro": perimetro_estimado,
            "area": area_estimada
        }
        
    return None

def procesar_archivo_dxf(ruta_archivo):
    doc = ezdxf.readfile(ruta_archivo)
    msp = doc.modelspace()
    
    lineas_extraidas = []
    for entity in msp.query('LINE'):
        lineas_extraidas.append({
            'x1': entity.dxf.start.x,
            'y1': entity.dxf.start.y,
            'x2': entity.dxf.end.x,
            'y2': entity.dxf.end.y
        })
    
    geometria_circular = detectar_circulo_por_segmentos(lineas_extraidas)
    
    if geometria_circular:
        return geometria_circular
    else:
        return {"tipo": "LINEAS_MULTIPLES", "elementos": len(lineas_extraidas)}
