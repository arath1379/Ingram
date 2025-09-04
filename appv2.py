import os
import time
import uuid
import requests
from flask import Flask, request, jsonify, render_template_string
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Credenciales de API (poner en .env)
CLIENT_ID = os.getenv("INGRAM_CLIENT_ID")
CLIENT_SECRET = os.getenv("INGRAM_CLIENT_SECRET")

# Credenciales Google Custom Search
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")

# Token global
TOKEN = None
TOKEN_EXPIRY = 0

# Cache simple para imágenes de Google (evita repetir las mismas búsquedas)
GOOGLE_IMAGE_CACHE = {}
CACHE_EXPIRY = 3600  # 1 hora en segundos

# Diccionario de logos de marcas conocidas
BRAND_LOGOS = {
    "hp": "https://upload.wikimedia.org/wikipedia/commons/2/29/HP_New_Logo_2D.svg",
    "hewlett packard": "https://upload.wikimedia.org/wikipedia/commons/2/29/HP_New_Logo_2D.svg",
    "dell": "https://upload.wikimedia.org/wikipedia/commons/4/48/Dell_Logo.svg",
    "cisco": "https://upload.wikimedia.org/wikipedia/commons/6/64/Cisco_logo.svg",
    "microsoft": "https://upload.wikimedia.org/wikipedia/commons/4/44/Microsoft_logo.svg",
    "lenovo": "https://upload.wikimedia.org/wikipedia/commons/4/45/Lenovo_Logo_2023.svg",
    "apple": "https://upload.wikimedia.org/wikipedia/commons/f/fa/Apple_logo_black.svg",
    "samsung": "https://upload.wikimedia.org/wikipedia/commons/2/24/Samsung_Logo.svg",
    "lg": "https://upload.wikimedia.org/wikipedia/commons/2/20/LG_symbol.svg",
    "asus": "https://upload.wikimedia.org/wikipedia/commons/9/96/Asus_logo_2023.svg",
    "acer": "https://upload.wikimedia.org/wikipedia/commons/5/5d/Acer_2011.svg",
    "intel": "https://upload.wikimedia.org/wikipedia/commons/0/0e/Intel_logo_2020.svg",
    "amd": "https://upload.wikimedia.org/wikipedia/commons/7/7c/AMD_Logo.svg",
    "nvidia": "https://upload.wikimedia.org/wikipedia/commons/5/58/Nvidia_logo.svg",
    "logitech": "https://upload.wikimedia.org/wikipedia/commons/7/75/Logitech_logo.svg",
    "kingston": "https://upload.wikimedia.org/wikipedia/commons/9/95/Kingston_Technology_logo.svg",
    "seagate": "https://upload.wikimedia.org/wikipedia/commons/8/8a/Seagate_Technology_logo.svg",
    "western digital": "https://upload.wikimedia.org/wikipedia/commons/2/2f/Western_Digital_logo.svg",
    "tp-link": "https://upload.wikimedia.org/wikipedia/commons/5/5c/TP-Link_Logo_2023.svg",
    "linksys": "https://upload.wikimedia.org/wikipedia/commons/0/04/Linksys_logo_2014.svg",
    "netgear": "https://upload.wikimedia.org/wikipedia/commons/4/49/Netgear_logo.svg",
    "canon": "https://upload.wikimedia.org/wikipedia/commons/4/42/Canon_logo.svg",
    "epson": "https://upload.wikimedia.org/wikipedia/commons/3/3c/Epson_logo_2015.svg",
    "brother": "https://upload.wikimedia.org/wikipedia/commons/5/5f/Brother_Industries_logo.svg",
    "ibm": "https://upload.wikimedia.org/wikipedia/commons/5/51/IBM_logo.svg",
    "sony": "https://upload.wikimedia.org/wikipedia/commons/c/ca/Sony_logo.svg",
    "panasonic": "https://upload.wikimedia.org/wikipedia/commons/3/35/Panasonic_logo_2011.svg",
    "philips": "https://upload.wikimedia.org/wikipedia/commons/3/33/Philips_New_Logo.svg",
    "jabra": "https://upload.wikimedia.org/wikipedia/commons/6/6a/Jabra_logo.svg",
    "plantronics": "https://upload.wikimedia.org/wikipedia/commons/9/9c/Plantronics_logo.svg",
    "poly": "https://upload.wikimedia.org/wikipedia/commons/9/9c/Plantronics_logo.svg",
    "aruba": "https://upload.wikimedia.org/wikipedia/commons/0/0e/Aruba_logo.svg",
    "fortinet": "https://upload.wikimedia.org/wikipedia/commons/9/95/Fortinet_logo.svg",
    "vmware": "https://upload.wikimedia.org/wikipedia/commons/5/5a/Vmware_logo.svg",
    "adobe": "https://upload.wikimedia.org/wikipedia/commons/6/6b/Adobe_Corporate_logo.svg",
    "autodesk": "https://upload.wikimedia.org/wikipedia/commons/5/59/Autodesk_Logo_2023.svg",
    "symantec": "https://upload.wikimedia.org/wikipedia/commons/d/d2/Symantec_logo10.png",
    "trend micro": "https://upload.wikimedia.org/wikipedia/commons/3/3e/Trend_Micro_logo.svg",
    "kaspersky": "https://upload.wikimedia.org/wikipedia/commons/a/a6/Kaspersky_Lab_logo.svg",
    "mcafee": "https://upload.wikimedia.org/wikipedia/commons/2/2e/McAfee_logo.svg",
    "sophos": "https://upload.wikimedia.org/wikipedia/commons/7/79/Sophos_logo.svg",
    "citrix": "https://upload.wikimedia.org/wikipedia/commons/8/86/Citrix_Systems_Logo_2021.svg",
    "manhattan": "https://www.manhattan-products.com/wp-content/themes/manhattan/img/logo.svg"
}


def get_token():
    """Obtiene y refresca el token de Ingram (cached)."""
    global TOKEN, TOKEN_EXPIRY
    if TOKEN and time.time() < TOKEN_EXPIRY:
        return TOKEN

    url = "https://api.ingrammicro.com/oauth/oauth20/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    res = requests.post(url, data=data, headers=headers)
    res.raise_for_status()
    token_data = res.json()

    TOKEN = token_data["access_token"]
    TOKEN_EXPIRY = time.time() + int(token_data.get("expires_in", 86399))
    return TOKEN


def ingram_headers():
    """Construye headers requeridos por Ingram."""
    correlation_id = str(uuid.uuid4()).replace("-", "")[:32]
    return {
        "Authorization": f"Bearer {get_token()}",
        "IM-CustomerNumber": os.getenv("INGRAM_CUSTOMER_NUMBER"),
        "IM-SenderID": os.getenv("INGRAM_SENDER_ID"),
        "IM-CorrelationID": correlation_id,
        "IM-CountryCode": os.getenv("INGRAM_COUNTRY_CODE"),
        "Accept-Language": os.getenv("INGRAM_LANGUAGE", "es-MX"),
        "Content-Type": "application/json"
    }


def format_currency(amount, currency_code):
    """Formatea un número con 2 decimales y prefija el código de moneda si existe."""
    if amount is None:
        return None
    try:
        amt = float(amount)
        code = f"{currency_code} " if currency_code else ""
        return f"{code}{amt:,.2f}"
    except Exception:
        return str(amount)


def get_availability_text(precio_info, detalle=None):
    """
    Genera un string amigable de disponibilidad.
    Usa: precio_info['availability'] preferente, luego detalle['availability'], luego productStatusCode/message.
    """
    av = None
    if isinstance(precio_info, dict):
        av = precio_info.get("availability")
    if not av and detalle and isinstance(detalle, dict):
        av = detalle.get("availability")

    # Si existe objeto availability -> interpretar
    if av and isinstance(av, dict):
        # intentar obtener totalAvailability
        total = None
        try:
            t = av.get("totalAvailability")
            if t is None:
                # si no viene, sumar availabilityByWarehouse
                byws = av.get("availabilityByWarehouse") or []
                total = sum(int(w.get("quantityAvailable", 0) or 0) for w in byws) if byws else None
            else:
                total = int(t) if isinstance(t, (int, float, str)) and str(t).strip() != "" else None
        except Exception:
            total = None

        available_flag = av.get("available")
        # si hay al menos unidades or flag true -> disponible
        if (isinstance(total, int) and total > 0) or available_flag:
            # construir lista de almacenes con stock
            byws = av.get("availabilityByWarehouse") or []
            warehouses = []
            for w in byws:
                q = int(w.get("quantityAvailable", 0) or 0)
                if q > 0:
                    loc = w.get("location") or w.get("warehouseName") or f"Almacén {w.get('warehouseId','?')}"
                    warehouses.append(f"{loc}: {q}")
            if total is None and warehouses:
                total = sum(int(x.split(":")[-1].strip()) for x in warehouses)
            if warehouses:
                # mostrar hasta 3 almacenes como ejemplo
                return f"Disponible — {total if total is not None else ''} unidades (ej. {', '.join(warehouses[:3])})"
            return f"Disponible — {total} unidades" if total is not None else "Disponible"
        else:
            return "Agotado"

    # fallback: usar productStatusCode / productStatusMessage
    if isinstance(precio_info, dict):
        code = precio_info.get("productStatusCode")
        msg = precio_info.get("productStatusMessage")
        if code:
            if code == "E":
                return msg or "No encontrado"
            # 'W' y otros códigos: mostrar mensaje si existe, sino una nota genérica.
            return msg or f"Estado: {code}"
    return "No disponible"


def get_brand_logo(brand_name):
    """Obtiene el logo de una marca conocida o None si no se encuentra."""
    if not brand_name:
        return None
    
    brand_lower = brand_name.strip().lower()
    
    # Buscar coincidencia exacta
    for brand_key, logo_url in BRAND_LOGOS.items():
        if brand_key == brand_lower:
            return logo_url
    
    # Buscar coincidencia parcial
    for brand_key, logo_url in BRAND_LOGOS.items():
        if brand_key in brand_lower or brand_lower in brand_key:
            return logo_url
    
    return None


def get_google_image(query: str):
    """Busca una imagen en Google Custom Search (modo imagen)."""
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        print("Google API credentials not configured")
        return None

    # Verificar cache primero
    cache_key = f"google_{hash(query)}"
    if cache_key in GOOGLE_IMAGE_CACHE:
        cached_data = GOOGLE_IMAGE_CACHE[cache_key]
        if time.time() < cached_data["expiry"]:
            return cached_data["url"]
        else:
            # Eliminar entrada expirada
            del GOOGLE_IMAGE_CACHE[cache_key]

    try:
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "q": query,
            "cx": GOOGLE_CSE_ID,
            "key": GOOGLE_API_KEY,
            "searchType": "image",
            "num": 3,
            "safe": "active",
            "rights": "cc_publicdomain"  # Solo imágenes con derechos de uso
        }
        r = requests.get(url, params=params, timeout=10)
        
        if r.status_code == 200:
            data = r.json()
            items = data.get("items", [])
            if items:
                # Buscar la primera imagen que tenga formato válido
                for item in items:
                    image_url = item.get("link")
                    if image_url and _is_valid_image_url(image_url):
                        # Guardar en cache
                        GOOGLE_IMAGE_CACHE[cache_key] = {
                            "url": image_url,
                            "expiry": time.time() + CACHE_EXPIRY
                        }
                        return image_url
        elif r.status_code == 403:
            print("Google API Error: Quota exceeded or invalid credentials")
        elif r.status_code == 429:
            print("Google API Error: Rate limit exceeded")
        else:
            print(f"Google API Error: Status code {r.status_code}")
            
    except requests.exceptions.Timeout:
        print("Google API Error: Request timeout")
    except requests.exceptions.RequestException as e:
        print(f"Google API Error: {e}")
    except Exception as e:
        print(f"Unexpected error in Google API: {e}")

    return None


def _is_valid_image_url(url):
    """Valida que la URL sea una imagen válida."""
    if not url or not url.startswith(('http://', 'https://')):
        return False
    
    # Filtrar dominios problemáticos
    blocked_domains = ['facebook.com', 'instagram.com', 'pinterest.com', 'twitter.com', 'youtube.com']
    if any(domain in url.lower() for domain in blocked_domains):
        return False
    
    # Verificar extensiones de imagen comunes
    valid_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']
    if any(url.lower().endswith(ext) for ext in valid_extensions):
        return True
    
    # Verificar si contiene indicadores de imagen en la URL
    image_indicators = ['/images/', 'image', 'img', 'photo']
    if any(indicator in url.lower() for indicator in image_indicators):
        return True
        
    return False


def get_image_url_enhanced(item):
    """
    Función mejorada que busca imágenes usando Google Custom Search como fallback.
    Intenta Ingram primero, luego busca externamente si no encuentra.
    """
    
    # 1. Intentar imagen de Ingram primero
    try:
        imgs = item.get("productImages") or item.get("productImageList") or []
        if imgs and isinstance(imgs, list) and len(imgs) > 0:
            first = imgs[0]
            ingram_url = first.get("url") or first.get("imageUrl") or first.get("imageURL")
            if ingram_url and "placeholder" not in ingram_url.lower() and _is_valid_image_url(ingram_url):
                return ingram_url
    except Exception:
        pass
    
    # 2. Buscar imagen externa usando Google Custom Search solo si tenemos credenciales
    producto_nombre = item.get("description", "")
    marca = item.get("vendorName", "")
    sku = item.get("ingramPartNumber", "")
    
    if not (producto_nombre or sku):
        # 3. Intentar obtener logo de la marca
        brand_logo = get_brand_logo(marca)
        if brand_logo:
            return brand_logo
        return "https://via.placeholder.com/300x300/f8f9fa/6c757d?text=Sin+Datos"
    
    # Construir queries de búsqueda específicas
    search_queries = []
    
    # Prioridad 1: Búsqueda específica con marca + SKU + descripción
    if marca and sku and producto_nombre:
        # Tomar las primeras palabras clave de la descripción
        palabras_desc = producto_nombre.split()[:5]
        desc_keywords = " ".join(palabras_desc)
        search_queries.append(f"{marca} {sku} {desc_keywords}")
    
    # Prioridad 2: Búsqueda con marca + descripción completa
    if marca and producto_nombre:
        search_queries.append(f"{marca} {producto_nombre}")
    
    # Prioridad 3: Búsqueda con SKU + descripción
    if sku and producto_nombre:
        search_queries.append(f"{sku} {producto_nombre}")
    
    # Prioridad 4: Búsqueda solo con SKU
    if sku:
        search_queries.append(f"{sku} producto")
    
    # Prioridad 5: Búsqueda solo con descripción
    if producto_nombre:
        search_queries.append(f"{producto_nombre} producto")
    
    # Intentar con Google Images si tenemos credenciales
    if GOOGLE_API_KEY and GOOGLE_CSE_ID:
        try:
            # Probar diferentes queries hasta encontrar una imagen
            for search_query in search_queries[:4]:  # Limitar a 4 intentos
                google_image = get_google_image(search_query)
                if google_image:
                    return google_image
        except Exception as e:
            print(f"Error buscando imagen para {sku}: {e}")
    
    # 3. Intentar obtener logo de la marca como fallback
    brand_logo = get_brand_logo(marca)
    if brand_logo:
        return brand_logo
    
    # 4. Fallback final - placeholder con nombre de marca si existe
    if marca:
        return f"https://via.placeholder.com/300x300/f8f9fa/6c757d?text={marca.replace(' ', '+')}"
    else:
        return "https://via.placeholder.com/300x300/f8f9fa/6c757d?text=Sin+Imagen"


def buscar_productos_hibrido(query="", vendor="", page_number=1, page_size=25):
    """
    Búsqueda híbrida que combina el catálogo general con búsqueda específica por SKU/número de parte.
    """
    productos_finales = []
    total_records = 0
    
    # 1. Si la query parece un SKU específico (menos de 30 caracteres, sin espacios múltiples)
    if query and len(query.strip()) < 30 and len(query.strip().split()) <= 3:
        # Intentar búsqueda directa por SKU usando price & availability
        productos_sku = buscar_por_sku_directo(query.strip())
        if productos_sku:
            productos_finales.extend(productos_sku)
            total_records += len(productos_sku)
    
    # 2. Búsqueda en catálogo general (siempre se ejecuta para complementar)
    productos_catalogo, records_catalogo, pagina_vacia = buscar_en_catalogo_general(query, vendor, page_number, page_size)
    
    # Evitar duplicados basados en ingramPartNumber
    skus_existentes = {p.get('ingramPartNumber') for p in productos_finales if p.get('ingramPartNumber')}
    for producto in productos_catalogo:
        if producto.get('ingramPartNumber') not in skus_existentes:
            productos_finales.append(producto)
    
    total_records += records_catalogo
    
    # Si la página está vacía pero hay total_records, ajustar
    if pagina_vacia and total_records > 0:
        # Estimar el total real basado en la página actual
        total_real_estimado = (page_number - 1) * page_size
        if total_real_estimado < total_records:
            total_records = total_real_estimado
    
    return productos_finales, total_records, pagina_vacia


def buscar_por_sku_directo(sku_query):
    """
    Busca productos usando el endpoint de price & availability con SKUs potenciales.
    """
    productos = []
    
    # Generar variantes del SKU (común que los usuarios no pongan el formato exacto)
    sku_variants = [
        sku_query,
        sku_query.upper(),
        sku_query.lower(),
        sku_query.replace(" ", ""),
        sku_query.replace("-", ""),
        sku_query.replace("_", ""),
    ]
    
    # Remover duplicados manteniendo orden
    sku_variants = list(dict.fromkeys(sku_variants))
    
    # Intentar con cada variante (máximo 5 para no saturar la API)
    for sku in sku_variants[:5]:
        try:
            url = "https://api.ingrammicro.com/resellers/v6/catalog/priceandavailability"
            body = {"products": [{"ingramPartNumber": sku}]}
            params = {
                "includeAvailability": "true",
                "includePricing": "true",
                "includeProductAttributes": "true"
            }
            
            res = requests.post(url, headers=ingram_headers(), params=params, json=body)
            
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and data:
                    producto_info = data[0]
                    
                    # Verificar que el producto existe y no tiene error
                    if (producto_info.get("productStatusCode") != "E" and 
                        producto_info.get("ingramPartNumber")):
                        
                        # Obtener detalles adicionales del producto
                        detalle = obtener_detalle_producto(producto_info.get("ingramPartNumber"))
                        
                        # Combinar información
                        producto_combinado = {
                            "ingramPartNumber": producto_info.get("ingramPartNumber"),
                            "description": (detalle.get("description") or 
                                          producto_info.get("description") or 
                                          "Descripción no disponible"),
                            "vendorName": (detalle.get("vendorName") or 
                                         producto_info.get("vendorName") or 
                                         "Marca no disponible"),
                            "productImages": detalle.get("productImages", []),
                            "pricing": producto_info.get("pricing", {}),
                            "availability": producto_info.get("availability", {}),
                            "productStatusCode": producto_info.get("productStatusCode"),
                            "productStatusMessage": producto_info.get("productStatusMessage")
                        }
                        productos.append(producto_combinado)
                        
        except Exception as e:
            print(f"Error buscando SKU {sku}: {e}")
            continue
    
    return productos


def obtener_detalle_producto(part_number):
    """
    Obtiene los detalles de un producto específico.
    """
    try:
        detail_url = f"https://api.ingrammicro.com/resellers/v6/catalog/details/{part_number}"
        detalle_res = requests.get(detail_url, headers=ingram_headers())
        return detalle_res.json() if detalle_res.status_code == 200 else {}
    except Exception:
        return {}


def buscar_en_catalogo_general(query="", vendor="", page_number=1, page_size=25):
    """
    Búsqueda en el catálogo general usando el endpoint GET.
    """
    url = "https://api.ingrammicro.com/resellers/v6/catalog"
    
    params = {
        "pageSize": page_size,
        "pageNumber": page_number,
        "showGroupInfo": "false"
    }
    
    if query:
        params["searchString"] = query
        params["searchInDescription"] = "true"
    if vendor:
        params["vendorName"] = vendor
    
    try:
        res = requests.get(url, headers=ingram_headers(), params=params)
        data = res.json() if res.status_code == 200 else {}
        
        productos = data.get("catalog", []) if isinstance(data, dict) else []
        total_records = data.get("recordsFound", 0)
        
        # Detectar si la página está vacía (no hay productos reales)
        pagina_vacia = len(productos) == 0
        
        return productos, total_records, pagina_vacia
        
    except Exception as e:
        print(f"Error en búsqueda de catálogo: {e}")
        return [], 0, True


@app.route("/catalogo-completo-cards", methods=["GET"])
def catalogo_completo_cards():
    # Parámetros de búsqueda
    page_number = int(request.args.get("page", 1))
    page_size = 25
    query = request.args.get("q", "").strip()
    vendor = request.args.get("vendor", "").strip()
    
    # Usar búsqueda híbrida
    productos, total_records, pagina_vacia = buscar_productos_hibrido(query, vendor, page_number, page_size)
    
    # Manejo inteligente de la paginación
    if pagina_vacia and page_number > 1:
        # Si la página está vacía, estimar el total real
        total_real_estimado = max(0, (page_number - 1) * page_size)
        total_records = total_real_estimado
    
    # Aplicar límite máximo conservador para evitar páginas infinitas
    MAX_RECORDS_LIMIT = 10000  # Límite conservador basado en limitaciones típicas de APIs
    if total_records > MAX_RECORDS_LIMIT:
        total_records = MAX_RECORDS_LIMIT
    
    # Cálculos para paginación ajustados
    total_pages = max(1, (total_records // page_size) + (1 if total_records % page_size else 0))
    
    # Ajustar página actual si excede el límite real
    if pagina_vacia and page_number > total_pages:
        page_number = total_pages
    
    start_record = (page_number - 1) * page_size + 1 if total_records > 0 else 0
    end_record = min(page_number * page_size, total_records)
    
    # Si no hay productos en esta página, ajustar la información mostrada
    if pagina_vacia and page_number > 1:
        end_record = start_record - 1
        start_record = 0

    html_template = """
    <html>
    <head>
        <title>Catálogo Ingram - Página {{ page_number }}</title>
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; background: #f9f9f9; }
            h2 { margin-bottom: 10px; color: #2c3e50; }
            .search-info { background: #e8f4fd; padding: 10px; border-radius: 8px; margin-bottom: 15px; color: #2980b9; font-size: 14px; }
            form.search-bar { margin-bottom: 20px; display:flex; gap:8px; }
            form.search-bar input[type=text] { padding: 8px; flex:1; border:1px solid #ddd; border-radius: 6px; font-size: 14px; }
            form.search-bar button { padding: 8px 16px; border:none; border-radius: 6px; background:#3498db; color:#fff; cursor:pointer; font-size: 14px; }
            form.search-bar button:hover { background:#2980b9; }
            .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 18px; }
            .card { background: #fff; border: 1px solid #e0e0e0; border-radius: 12px; overflow: hidden; 
                    box-shadow: 0 2px 8px rgba(0,0,0,0.08); text-decoration: none; color: inherit; 
                    transition: transform 0.2s, box-shadow 0.2s; }
            .card:hover { transform: translateY(-2px); box-shadow: 0 4px 15px rgba(0,0,0,0.15); }
            .card img { width: 100%; height: 200px; object-fit: contain; background: #f8f9fa; }
            .card-content { padding: 15px; }
            .card h4 { margin: 0 0 8px 0; font-size: 15px; color: #2c3e50; height: 40px; overflow: hidden; line-height: 1.3; }
            .card p { margin: 4px 0; font-size: 13px; color: #7f8c8d; }
            .card .sku { font-family: monospace; background: #ecf0f1; padding: 2px 6px; border-radius: 4px; font-size: 12px; }
            .card .price { color: #27ae60; font-weight: bold; font-size: 14px; margin-top: 8px; }
            .card .availability { font-size: 12px; color: #e67e22; }
            .pagination { margin-top: 25px; text-align: center; font-size: 14px; color: #555; }
            .pagination a, .pagination button { margin: 0 8px; padding: 8px 16px; background: #3498db; color: white; 
                                               border-radius: 6px; text-decoration: none; border:none; cursor:pointer; }
            .pagination a.disabled { background: #bdc3c7; pointer-events: none; }
            .pagination a:hover:not(.disabled) { background: #2980b9; }
            .goto-form { margin-top: 15px; }
            .goto-form input { width: 70px; padding:6px; border:1px solid #bdc3c7; border-radius: 6px; text-align:center; }
        </style>
    </head>
    <body>
        <h2>Catálogo de Productos</h2>
        
        {% if query or vendor %}
        <div class="search-info">
            <strong>Búsqueda activa:</strong>
            {% if query %}Texto: "{{ query }}"{% endif %}
            {% if vendor %}| Marca: "{{ vendor }}"{% endif %}
            | Búsqueda híbrida (catálogo + SKU directo)
        </div>
        {% endif %}

        <!-- Barra de búsqueda -->
        <form method="get" class="search-bar">
            <input type="text" name="q" placeholder="Buscar por nombre, descripción, SKU o número de parte..." value="{{ query }}">
            <input type="text" name="vendor" placeholder="Filtrar por marca (ej: HP, Dell, Cisco)..." value="{{ vendor }}">
            <button type="submit">🔍 Buscar</button>
            <a href="/catalogo-completo-cards" style="padding: 8px 16px; background: #95a5a6; color: white; text-decoration: none; border-radius: 6px;">Limpiar</a>
        </form>

        <p><strong>Mostrando {{ start_record }} a {{ end_record }} de {{ total_records }} registros</strong></p>
        <p>Página {{ page_number }} de {{ total_pages }}</p>

        {% if pagina_vacia and page_number > 1 %}
        <div style="background: #fff3cd; border: 1px solid #ffeaa7; color: #856404; padding: 15px; border-radius: 8px; margin: 20px 0; text-align: center;">
            <h3>📄 Página sin resultados</h3>
            <p>No hay más productos disponibles en esta página. La API tiene limitaciones de paginación.</p>
            <a href="?page=1&q={{ query }}&vendor={{ vendor }}" style="padding: 8px 16px; background: #007bff; color: white; text-decoration: none; border-radius: 6px;">Volver a la página 1</a>
        </div>
        {% elif not productos %}
        <div style="background: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; padding: 20px; border-radius: 8px; margin: 20px 0; text-align: center;">
            <h3>🔍 Sin resultados</h3>
            <p>No se encontraron productos que coincidan con tu búsqueda.</p>
            <p><strong>Sugerencias:</strong></p>
            <ul style="text-align: left; max-width: 400px; margin: 0 auto;">
                <li>Verifica la ortografía</li>
                <li>Intenta términos más generales</li>
                <li>Busca por marca específica</li>
                <li>Prueba con el número de parte exacto</li>
            </ul>
        </div>
        {% endif %}

        <div class="grid">
            {% for p in productos %}
            <a class="card" href="/producto/{{ p.get('ingramPartNumber') }}">
                <img src="{{ get_image_url_enhanced(p) }}" alt="Imagen del producto" loading="lazy">
                <div class="card-content">
                    <h4>{{ p.get('description', 'Sin descripción') }}</h4>
                    <p><strong>SKU:</strong> <span class="sku">{{ p.get('ingramPartNumber', 'N/A') }}</span></p>
                    <p><strong>Marca:</strong> {{ p.get('vendorName', 'No disponible') }}</p>
                    
                    {% if p.get('pricing') and p.get('pricing').get('customerPrice') %}
                        {% set precio_base = p.get('pricing').get('customerPrice') %}
                        {% set moneda = p.get('pricing').get('currencyCode', '') %}
                        {% set precio_final = (precio_base * 1.10) | round(2) %}
                        <p class="price">{{ moneda }} {{ precio_final | round(2) }}</p>
                    {% endif %}
                    
                    {% if p.get('availability') %}
                        <p class="availability">{{ get_availability_text(p) }}</p>
                    {% endif %}
                </div>
            </a>
            {% endfor %}
        </div>

        <!-- Navegación -->
        <div class="pagination">
            {% if page_number > 1 %}
                <a href="?page={{ page_number - 1 }}&q={{ query }}&vendor={{ vendor }}">⬅ Anterior</a>
            {% else %}
                <a class="disabled">⬅ Anterior</a>
            {% endif %}

            {% if page_number < total_pages %}
                <a href="?page={{ page_number + 1 }}&q={{ query }}&vendor={{ vendor }}">Siguiente ➡</a>
            {% else %}
                <a class="disabled">Siguiente ➡</a>
            {% endif %}
        </div>

        <!-- Ir a página específica -->
        <div class="goto-form" style="text-align:center;">
            <form method="get">
                <input type="hidden" name="q" value="{{ query }}">
                <input type="hidden" name="vendor" value="{{ vendor }}">
                <label>Ir a página: </label>
                <input type="number" name="page" min="1" max="{{ total_pages }}" value="{{ page_number }}">
                <button type="submit">Ir</button>
            </form>
        </div>
    </body>
    </html>
    """
    
    return render_template_string(
        html_template,
        productos=productos,
        get_image_url_enhanced=get_image_url_enhanced,
        get_availability_text=get_availability_text,
        page_number=page_number,
        total_records=total_records,
        total_pages=total_pages,
        start_record=start_record,
        end_record=end_record,
        query=query,
        vendor=vendor,
        pagina_vacia=pagina_vacia
    )


# Endpoint para búsqueda por AJAX (opcional, para implementar búsqueda en tiempo real)
@app.route("/api/buscar", methods=["POST"])
def api_buscar():
    data = request.get_json()
    query = data.get("query", "").strip()
    vendor = data.get("vendor", "").strip()
    page = data.get("page", 1)
    
    productos, total, pagina_vacia = buscar_productos_hibrido(query, vendor, page, 25)
    
    return jsonify({
        "productos": productos,
        "total": total,
        "page": page,
        "pagina_vacia": pagina_vacia
    })


# ---------- DETALLE DE PRODUCTO ----------
@app.route("/producto/<part_number>", methods=["GET"])
def producto_detalle(part_number):
    # Detalle (catalog/details)
    detail_url = f"https://api.ingrammicro.com/resellers/v6/catalog/details/{part_number}"
    detalle_res = requests.get(detail_url, headers=ingram_headers())
    detalle = detalle_res.json() if detalle_res.status_code == 200 else {}

    # Precio y disponibilidad (priceandavailability)
    price_url = "https://api.ingrammicro.com/resellers/v6/catalog/priceandavailability"
    body = {"products": [{"ingramPartNumber": part_number}]}
    params = {
        "includeAvailability": "true",
        "includePricing": "true",
        "includeProductAttributes": "true"
    }
    precio_res = requests.post(price_url, headers=ingram_headers(), params=params, json=body)
    precio = precio_res.json() if precio_res.status_code == 200 else []
    precio_info = precio[0] if isinstance(precio, list) and precio else (precio if isinstance(precio, dict) else {})

    # Obtener pricing y aplicar 10%
    pricing = precio_info.get("pricing") or {}
    base_price = pricing.get("customerPrice")
    currency = pricing.get("currencyCode") or pricing.get("currency") or ""
    precio_final_val = None
    if base_price is not None:
        try:
            precio_final_val = round(float(base_price) * 1.10, 2)
        except Exception:
            precio_final_val = None
    precio_final = format_currency(precio_final_val, currency) if precio_final_val is not None else "No disponible"

    # Disponibilidad interpretada
    disponibilidad = get_availability_text(precio_info, detalle)

    # Descripción larga y atributos (flexible con nombres)
    descripcion_larga = (
        detalle.get("longDescription")
        or detalle.get("productLongDescription")
        or detalle.get("productLongDescr")
        or detalle.get("description")
        or "Este producto ofrece calidad y rendimiento garantizado por Ingram Micro."
    )

    # Extraer atributos con formatos posibles
    atributos = []
    raw_attrs = detalle.get("productAttributes") or detalle.get("attributes") or []
    if isinstance(raw_attrs, list):
        for a in raw_attrs:
            # tratar distintos nombres de campo
            name = a.get("name") or a.get("attributeName") or a.get("key") or None
            value = a.get("value") or a.get("attributeValue") or a.get("val") or ""
            if name:
                atributos.append({"name": name, "value": value})

    # Usar la función mejorada con Google Images
    imagen_url = get_image_url_enhanced(detalle)

    # Render HTML
    html_template = """
    <html>
    <head>
        <title>{{ detalle.get('description', 'Detalle de Producto') }}</title>
        <meta charset="utf-8"/>
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; background: #fafafa; color: #333; }
            .container { background: #fff; padding: 20px; border-radius: 10px; box-shadow: 0 2px 6px rgba(0,0,0,0.08); max-width:1000px; margin: 0 auto; }
            .top { display:flex; gap:20px; align-items:flex-start; }
            .left { width: 300px; }
            .left img { width: 100%; height: auto; object-fit: contain; background:#f6f6f6; border:1px solid #eee; padding:10px; border-radius:6px;}
            .right { flex:1; }
            h2 { margin-top: 0; color: #222; }
            .etiqueta { font-weight: bold; color: #444; }
            .extra { margin-top: 15px; padding: 12px; background: #f7f7f8; border-radius: 8px; }
            ul { margin: 6px 0 0 18px; }
            .price { font-size: 20px; color: #111; font-weight: 700; margin: 8px 0; }
            .meta { color:#666; font-size:13px; margin-bottom:10px; }
            .back-btn { display: inline-block; padding: 8px 16px; background: #3498db; color: white; text-decoration: none; border-radius: 6px; margin-bottom: 15px; }
        </style>
    </head>
    <body>
        <a href="/catalogo-completo-cards" class="back-btn">⬅ Volver al catálogo</a>
        
        <div class="container">
            <div class="top">
                <div class="left">
                    <img src="{{ imagen_url }}" alt="Imagen del producto">
                </div>
                <div class="right">
                    <h2>{{ detalle.get('description', 'Sin descripción') }}</h2>
                    <div class="meta">
                        <span class="etiqueta">SKU Ingram:</span> {{ detalle.get('ingramPartNumber') or part_number }} &nbsp;|&nbsp;
                        <span class="etiqueta">Marca:</span> {{ detalle.get('vendorName', 'No disponible') }}
                    </div>

                    <div class="price">
                        {{ precio_final }}
                    </div>
                    <div class="meta"><span class="etiqueta">Disponibilidad:</span> {{ disponibilidad }}</div>

                    <div class="extra">
                        <h4>Descripción</h4>
                        <p style="margin:6px 0 0 0;">{{ descripcion_larga }}</p>
                    </div>

                    {% if atributos %}
                    <div class="extra" style="margin-top:12px;">
                        <h4>Características adicionales</h4>
                        <ul>
                            {% for a in atributos %}
                                <li><strong>{{ a.name }}:</strong> {{ a.value }}</li>
                            {% endfor %}
                        </ul>
                    </div>
                    {% endif %}

                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(
        html_template,
        detalle=detalle,
        precio_final=precio_final,
        disponibilidad=disponibilidad,
        descripcion_larga=descripcion_larga,
        atributos=atributos,
        imagen_url=imagen_url,
        part_number=part_number
    )


# Ruta de prueba para Google Images
@app.route("/test-google-image")
def test_google_image():
    query = request.args.get("q", "laptop hp")
    image_url = get_google_image(query)
    
    if image_url:
        return f'<h3>Resultado para "{query}":</h3><img src="{image_url}" width="300"><p>{image_url}</p>'
    else:
        return f'<h3>No se pudo obtener imagen para "{query}"</h3><p>Verifica las credenciales de Google API o intenta con otra consulta.</p>'


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)