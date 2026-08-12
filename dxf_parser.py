import math
import ezdxf

def procesar_archivo_dxf(ruta_archivo):
    doc = ezdxf.readfile(ruta_archivo)
    msp = doc.modelspace()
    
    lineas_extraidas = []
    
    # Capturar líneas directas
    for entity in msp.query('LINE'):
        lineas_extraidas.append((entity.dxf.start.x, entity.dxf.start.y, entity.dxf.end.x, entity.dxf.end.y))
        
    # Capturar polilíneas
    for polyl in msp.query('LWPOLYLINE'):
        puntos_poly = [(p[0], p[1]) for p in polyl.get_points(format='xy[sez]')]
        for i in range(len(puntos_poly) - 1):
            lineas_extraidas.append((puntos_poly[i][0], puntos_poly[i][1], puntos_poly[i+1][0], puntos_poly[i+1][1]))
        if polyl.closed and len(puntos_poly) > 2:
            lineas_extraidas.append((puntos_poly[-1][0], puntos_poly[-1][1], puntos_poly[0][0], puntos_poly[0][1]))

    total_elementos = len(lineas_extraidas)
    print(f"Total de segmentos encontrados: {total_elementos}")

    if total_elementos == 0:
        return {"tipo": "VACIO", "elementos": 0}

    # Si son miles de líneas (por ejemplo, más de 100), calculamos la caja contenedora (Bounding Box)
    # para entender el tamaño real de la pieza sin importar cuántos micro-segmentos tenga.
    min_x = min(min(l[0], l[2]) for l in lineas_extraidas)
    max_x = max(max(l[0], l[2]) for l in lineas_extraidas)
    min_y = min(min(l[1], l[3]) for l in lineas_extraidas)
    max_y = max(max(l[1], l[3]) for l in lineas_extraidas)

    ancho = max_x - min_x
    alto = max_y - min_y

    # Estimación geométrica inteligente basada en el contenedor
    if total_elementos > 100:
        # Probablemente sea una figura compleja o un círculo/rectángulo mallado
        # Estimamos perímetro aproximado sumando los bordes de la caja o la longitud acumulada de los trazos
        perimetro_acumulado = sum(math.hypot(l[2]-l[0], l[3]-l[1]) for l in lineas_extraidas)
        
        return {
            "tipo": "GEOMETRIA_MALLEADA_DETECTADA",
            "elementos": total_elementos,
            "ancho": round(ancho, 2),
            "alto": round(alto, 2),
            "perimetro": round(perimetro_acumulado, 2),
            "area_aproximada": round(ancho * alto, 2)
        }
    
    return {"tipo": "LINEAS_MULTIPLES", "elementos": total_elementos}
