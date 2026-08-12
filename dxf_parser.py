import math
import ezdxf

def detectar_circulo_por_segmentos(lineas, tolerancia=0.05):
    """
    Analiza una lista de segmentos de línea para detectar si forman un círculo
    y extrae su centro y radio aproximado.
    """
    if not lineas or len(lineas) < 4:
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
    
    # Imprimir cuántas entidades de cada tipo encuentra en el archivo
    print(f"--- ANALIZANDO: {ruta_archivo} ---")
    print(f"LINEAS directas: {len(msp.query('LINE'))}")
    print(f"LWPOLYLINES: {len(msp.query('LWPOLYLINE'))}")
    print(f"CIRCLES: {len(msp.query('CIRCLE'))}")
    print(f"ARCS: {len(msp.query('ARC'))}")
    
    # 1. Capturar líneas
    for entity in msp.query('LINE'):
        lineas_extraidas.append({
            'x1': entity.dxf.start.x,
            'y1': entity.dxf.start.y,
            'x2': entity.dxf.end.x,
            'y2': entity.dxf.end.y
        })
        
    # 2. Capturar polilíneas de forma segura
    for polyl in msp.query('LWPOLYLINE'):
        # Usamos get_points() con formato de coordenadas (x, y)
        puntos_poly = [(p[0], p[1]) for p in polyl.get_points(format='xy[sez]')]
        for i in range(len(puntos_poly) - 1):
            lineas_extraidas.append({
                'x1': puntos_poly[i][0],
                'y1': puntos_poly[i][1],
                'x2': puntos_poly[i+1][0],
                'y2': puntos_poly[i+1][1]
            })
        if polyl.closed and len(puntos_poly) > 2:
            lineas_extraidas.append({
                'x1': puntos_poly[-1][0],
                'y1': puntos_poly[-1][1],
                'x2': puntos_poly[0][0],
                'y2': puntos_poly[0][1]
            })

    # 3. Círculos nativos
    for circ in msp.query('CIRCLE'):
        radio = circ.dxf.radius
        centro = circ.dxf.center
        return {
            "tipo": "CIRCULO_DETECTADO",
            "centro": (centro.x, centro.y),
            "radio": radio,
            "perimetro": 2 * math.pi * radio,
            "area": math.pi * (radio ** 2)
        }

    geometria_circular = detectar_circulo_por_segmentos(lineas_extraidas)
    
    if geometria_circular:
        return geometria_circular
    else:
        return {"tipo": "LINEAS_MULTIPLES", "elementos": len(lineas_extraidas)}
