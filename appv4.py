import os
import time
import uuid
import requests
import re
import json
from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for
from dotenv import load_dotenv
from unidecode import unidecode

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'una-clave-secreta-muy-segura-para-desarrollo')

# Credenciales de API (poner en .env)
CLIENT_ID = os.getenv("INGRAM_CLIENT_ID")
CLIENT_SECRET = os.getenv("INGRAM_CLIENT_SECRET")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

# Token global
TOKEN = None
TOKEN_EXPIRY = 0

# Diccionario de normalización de marcas (ampliado)
BRAND_NORMALIZATION = {
    'perfect choice': 'Perfect Choice',
    'perfectchoice': 'Perfect Choice',
    'pchoice': 'Perfect Choice',
    'p-choice': 'Perfect Choice',
    'perfecto grote': 'Perfect Choice',
    'perfecto': 'Perfect Choice',
    'grote': 'Perfect Choice',
    # Puedes agregar más normalizaciones aquí
    'acteck': 'Acteck',
    'ax': 'Acteck',
    'ax-': 'Acteck',
    'haken': 'Haken',
    'hak': 'Haken',
}

# Diccionario de sinónimos para búsquedas
PRODUCT_SYNONYMS = {
    'kit': ['set', 'combo', 'pack', 'bundle'],
    'teclado': ['keyboard'],
    'mouse': ['ratón', 'raton'],
    'alámbrico': ['cable', 'cabled', 'wired'],
    'inalámbrico': ['wireless', 'sin cable'],
    'audífonos': ['auriculares', 'headphones', 'headset'],
    'bt': ['bluetooth'],
    'tws': ['true wireless', 'true wireless stereo'],
    'derrames': ['spills', 'liquid', 'water'],
    'resistente': ['resistant', 'spillproof', 'waterproof'],
    'usb': ['universal serial bus'],
}

# Inicializar carrito y favoritos en la sesión
@app.before_request
def before_request():
    if 'cart' not in session:
        session['cart'] = {}
    if 'wishlist' not in session:
        session['wishlist'] = {}

def normalize_text(text):
    """Normaliza texto para mejorar las coincidencias."""
    if not text:
        return ""
    
    # Convertir a minúsculas y quitar acentos
    text = unidecode(text.lower())
    
    # Eliminar caracteres especiales pero mantener espacios
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    
    # Reemplazar múltiples espacios por uno solo
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def normalize_brand(brand_name):
    """Normaliza nombres de marcas usando el diccionario de normalización."""
    if not brand_name:
        return ""
    
    normalized = normalize_text(brand_name)
    
    # Buscar en el diccionario de normalización
    for key, value in BRAND_NORMALIZATION.items():
        if key in normalized:
            return value
    
    # Si no encuentra coincidencia, intentar extraer la marca real
    # Algunas marcas vienen combinadas como "Perfecto Grote" - tomar la primera palabra
    words = normalized.split()
    if words:
        first_word = words[0]
        for key, value in BRAND_NORMALIZATION.items():
            if key.startswith(first_word):
                return value
    
    # Si no encuentra coincidencia, capitalizar palabras
    return brand_name.title()

def expand_search_terms(query):
    """Expande los términos de búsqueda usando sinónimos."""
    if not query:
        return query
    
    normalized_query = normalize_text(query)
    words = normalized_query.split()
    expanded_terms = []
    
    for word in words:
        if word in PRODUCT_SYNONYMS:
            expanded_terms.extend(PRODUCT_SYNONYMS[word])
        else:
            expanded_terms.append(word)
    
    # Devolver términos únicos
    return " ".join(list(set(expanded_terms)))

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

def get_image_url_enhanced(item):
    """
    Función mejorada que busca imágenes usando SerpApi como fallback.
    Intenta Ingram primero, luego busca externamente si no encuentra.
    """
    
    # 1. Intentar imagen de Ingram primero
    try:
        imgs = item.get("productImages") or item.get("productImageList") or []
        if imgs and isinstance(imgs, list) and len(imgs) > 0:
            first = imgs[0]
            ingram_url = first.get("url") or first.get("imageUrl") or first.get("imageURL")
            if ingram_url and "placeholder" not in ingram_url.lower():
                return ingram_url
    except Exception:
        pass
    
    # 2. Buscar imagen externa usando SerpApi
    serpapi_key = os.getenv("SERPAPI_KEY")
    if not serpapi_key:
        return "https://via.placeholder.com/300x300/f8f9fa/6c757d?text=Sin+Imagen"
    
    producto_nombre = item.get("description", "")
    marca = item.get("vendorName", "")
    sku = item.get("ingramPartNumber", "")
    
    if not (producto_nombre or sku):
        return "https://via.placeholder.com/300x300/f8f9fa/6c757d?text=Sin+Datos"
    
    try:
        # Construir query de búsqueda
        if marca and sku:
            search_query = f"{marca} {sku} product"
        elif marca and producto_nombre:
            # Limpiar nombre del producto (solo primeras 3 palabras)
            nombre_limpio = " ".join(producto_nombre.replace(",", "").replace("-", " ").split()[:3])
            search_query = f"{marca} {nombre_limpio}"
        elif sku:
            search_query = f"{sku} product image"
        else:
            nombre_limpio = " ".join(producto_nombre.replace(",", "").replace("-", " ").split()[:3])
            search_query = f"{nombre_limpio} product"
        
        # Llamada a SerpApi
        params = {
            "engine": "google_images",
            "q": search_query,
            "api_key": serpapi_key,
            "num": 3,
            "safe": "active"
        }
        
        response = requests.get("https://serpapi.com/search", params=params, timeout=8)
        
        if response.status_code == 200:
            data = response.json()
            images = data.get("images_results", [])
            
            for img in images:
                image_url = img.get("original") or img.get("thumbnail")
                if image_url and _is_valid_image(image_url):
                    return image_url
        
    except Exception as e:
        print(f"Error buscando imagen para {sku}: {e}")
    
    # 3. Fallback final
    return "https://via.placeholder.com/300x300/f8f9fa/6c757d?text=Sin+Imagen"

def _is_valid_image(url):
    """Valida que la URL sea una imagen válida."""
    if not url or not url.startswith(('http://', 'https://')):
        return False
    
    # Filtrar dominios problemáticos
    blocked = ['facebook.com', 'instagram.com', 'pinterest.com', 'twitter.com']
    if any(domain in url.lower() for domain in blocked):
        return False
    
    # Verificar indicadores de imagen
    indicators = ['.jpg', '.jpeg', '.png', '.gif', '.webp', 'image', 'img']
    return any(indicator in url.lower() for indicator in indicators)

def is_detailed_query(query):
    """
    Determina si una consulta es detallada (contiene múltiples especificaciones).
    Ej: "BOCINAS ACTECK PARA COMPUTO AX-2500 / 3.5 mm / Sonido Estereo 2"
    """
    if not query:
        return False
    
    # Verificar si contiene múltiples especificaciones separadas por "/" u otros delimitadores
    delimiters = r"[/|,-]"
    parts = re.split(delimiters, query)
    
    # Si tiene al menos 3 partes o más de 4 palabras, consideramos que es detallada
    if len(parts) >= 2 or len(query.split()) >= 5:
        return True
    
    # Verificar si contiene especificaciones técnicas comunes
    tech_indicators = [
        'mm', 'gb', 'tb', 'ghz', 'mhz', 'hz', 'w', 'v', 'mah', 
        'pulgadas', 'pulg', 'p', 'hd', 'full hd', '4k', '8k',
        'sonido', 'audio', 'estéreo', 'estereo', 'bluetooth', 'wifi'
    ]
    
    query_lower = query.lower()
    for indicator in tech_indicators:
        if indicator in query_lower:
            return True
    
    return False

def search_with_serpapi(detailed_query):
    """
    Realiza una búsqueda específica usando SerpApi para consultas detalladas.
    Devuelve una lista de SKUs o números de parte potenciales.
    """
    if not SERPAPI_KEY:
        print("Advertencia: No hay clave de SerpAPI configurada")
        return []
    
    try:
        # Preparar la consulta para SerpApi
        search_query = f"{detailed_query} site:ingrammicro.com OR site:ingrammicro.mx"
        
        params = {
            "engine": "google",
            "q": search_query,
            "api_key": SERPAPI_KEY,
            "num": 10,
            "safe": "active"
        }
        
        response = requests.get("https://serpapi.com/search", params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            organic_results = data.get("organic_results", [])
            
            # Extraer posibles SKUs o números de parte de los resultados
            potential_skus = []
            for result in organic_results:
                title = result.get("title", "").lower()
                snippet = result.get("snippet", "").lower()
                
                # Buscar patrones que parezcan SKUs (combinaciones de letras y números)
                sku_patterns = [
                    r'\b[a-z]{2,}\d{4,}\b',  # Ej: G59007H
                    r'\b\d+[a-z]+\d*\b',      # Ej: 2500ax
                    r'\b[a-z]+\d+[a-z]*\b',   # Ej: ax2500
                ]
                
                for pattern in sku_patterns:
                    matches = re.findall(pattern, title + " " + snippet)
                    potential_skus.extend(matches)
            
            # También buscar en la URL
            for result in organic_results:
                link = result.get("link", "")
                if "ingrammicro" in link:
                    # Extraer posibles SKUs de la URL
                    sku_from_url = re.findall(r'/([a-z0-9]{6,})[/-]', link, re.IGNORECASE)
                    potential_skus.extend(sku_from_url)
            
            # Devolver SKUs únicos
            return list(set([sku.upper() for sku in potential_skus]))
        
    except Exception as e:
        print(f"Error en búsqueda con SerpApi: {e}")
    
    return []

def mejorar_descripcion_producto(producto, query="", vendor=""):
    """
    Mejora la descripción del producto basándose en la consulta original.
    Intenta hacer coincidir mejor el nombre con lo que el usuario espera.
    """
    if not producto:
        return producto
    
    descripcion_original = producto.get('description', '')
    vendor_original = producto.get('vendorName', '')
    
    # Si tenemos una consulta, intentar mejorar la descripción
    if query:
        query_normalizada = normalize_text(query)
        desc_normalizada = normalize_text(descripcion_original)
        
        # Si la consulta contiene términos que no están en la descripción
        palabras_query = set(query_normalizada.split())
        palabras_desc = set(desc_normalizada.split())
        
        palabras_faltantes = palabras_query - palabras_desc
        
        if palabras_faltantes and len(palabras_faltantes) <= 3:
            # Agregar las palabras faltantes al inicio de la descripción
            palabras_agregar = " ".join(palabras_faltantes)
            producto['description'] = f"{palabras_agregar.title()} {descripcion_original}"
    
    # Normalizar la marca (más agresivamente)
    if vendor_original:
        # Primero intentar con el diccionario de normalización
        marca_normalizada = normalize_brand(vendor_original)
        
        # Si no se normalizó correctamente, intentar extraer la marca real
        if marca_normalizada == vendor_original.title():  # Si no cambió
            # Buscar patrones comunes de marcas en el texto
            palabras = vendor_original.lower().split()
            for palabra in palabras:
                for key, value in BRAND_NORMALIZATION.items():
                    if key in palabra:
                        marca_normalizada = value
                        break
                if marca_normalizada != vendor_original.title():
                    break
        
        producto['vendorName'] = marca_normalizada
    elif vendor:
        producto['vendorName'] = normalize_brand(vendor)
    
    return producto

def buscar_productos_hibrido(query="", vendor="", page_number=1, page_size=25):
    """
    Búsqueda híbrida que combina el catálogo general con búsqueda específica por SKU/número de parte.
    Ahora también incluye búsqueda con SerpApi para consultas detalladas.
    """
    productos_finales = []
    total_records = 0
    serpapi_skus = []
    
    # Normalizar consulta y vendor
    query_normalizada = query
    vendor_normalizado = normalize_brand(vendor) if vendor else ""
    
    # Expandir términos de búsqueda con sinónimos
    query_expandida = expand_search_terms(query)
    
    # 1. Si la consulta es detallada, usar SerpApi para encontrar SKUs potenciales
    if query and is_detailed_query(query):
        print(f"Consulta detallada detectada: {query}")
        serpapi_skus = search_with_serpapi(query)
        print(f"SKUs potenciales encontrados con SerpApi: {serpapi_skus}")
    
    # 2. Si la query parece un SKU específico o tenemos SKUs de SerpApi
    skus_to_search = []
    if query and len(query.strip()) < 30 and len(query.strip().split()) <= 3:
        skus_to_search.append(query.strip())
    
    # Agregar SKUs encontrados con SerpApi
    skus_to_search.extend(serpapi_skus)
    
    # Buscar por cada SKU potencial
    for sku in skus_to_search:
        productos_sku = buscar_por_sku_directo(sku)
        if productos_sku:
            for producto in productos_sku:
                producto_mejorado = mejorar_descripcion_producto(producto, query, vendor)
                productos_finales.append(producto_mejorado)
            total_records += len(productos_sku)
    
    # 3. Búsqueda en catálogo general (siempre se ejecuta para complementar)
    # Usar la consulta expandida para mejores resultados
    productos_catalogo, records_catalogo, pagina_vacia = buscar_en_catalogo_general(
        query_expandida, vendor_normalizado, page_number, page_size
    )
    
    # Mejorar descripciones de productos del catálogo
    productos_catalogo_mejorados = []
    for producto in productos_catalogo:
        producto_mejorado = mejorar_descripcion_producto(producto, query, vendor)
        productos_catalogo_mejorados.append(producto_mejorado)
    
    # Evitar duplicados basados en ingramPartNumber
    skus_existentes = {p.get('ingramPartNumber') for p in productos_finales if p.get('ingramPartNumber')}
    for producto in productos_catalogo_mejorados:
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

# Funciones para el carrito y favoritos
def add_to_cart(product_id, product_data, quantity=1):
    """Añade un producto al carrito."""
    cart = session.get('cart', {})
    if product_id in cart:
        cart[product_id]['quantity'] += quantity
    else:
        cart[product_id] = {
            'data': product_data,
            'quantity': quantity
        }
    session['cart'] = cart
    return True

def remove_from_cart(product_id):
    """Elimina un producto del carrito."""
    cart = session.get('cart', {})
    if product_id in cart:
        del cart[product_id]
        session['cart'] = cart
        return True
    return False

def add_to_wishlist(product_id, product_data):
    """Añade un producto a la lista de deseos."""
    wishlist = session.get('wishlist', {})
    wishlist[product_id] = product_data
    session['wishlist'] = wishlist
    return True

def remove_from_wishlist(product_id):
    """Elimina un producto de la lista de deseos."""
    wishlist = session.get('wishlist', {})
    if product_id in wishlist:
        del wishlist[product_id]
        session['wishlist'] = wishlist
        return True
    return False

# Rutas para el carrito y favoritos
@app.route("/add-to-cart/<product_id>", methods=["POST"])
def add_to_cart_route(product_id):
    quantity = int(request.form.get('quantity', 1))
    # Obtener datos del producto
    detail_url = f"https://api.ingrammicro.com/resellers/v6/catalog/details/{product_id}"
    detalle_res = requests.get(detail_url, headers=ingram_headers())
    detalle = detalle_res.json() if detalle_res.status_code == 200 else {}
    
    price_url = "https://api.ingrammicro.com/resellers/v6/catalog/priceandavailability"
    body = {"products": [{"ingramPartNumber": product_id}]}
    params = {"includePricing": "true"}
    precio_res = requests.post(price_url, headers=ingram_headers(), params=params, json=body)
    precio_info = precio_res.json()[0] if precio_res.status_code == 200 else {}
    
    product_data = {
        'id': product_id,
        'name': detalle.get('description', 'Producto sin nombre'),
        'price': precio_info.get('pricing', {}).get('customerPrice', 0),
        'currency': precio_info.get('pricing', {}).get('currencyCode', 'MXN'),
        'image': get_image_url_enhanced(detalle)
    }
    
    add_to_cart(product_id, product_data, quantity)
    return redirect(request.referrer or url_for('catalogo_completo_cards'))

@app.route("/remove-from-cart/<product_id>")
def remove_from_cart_route(product_id):
    remove_from_cart(product_id)
    return redirect(url_for('view_cart'))

@app.route("/add-to-wishlist/<product_id>")
def add_to_wishlist_route(product_id):
    # Obtener datos del producto
    detail_url = f"https://api.ingrammicro.com/resellers/v6/catalog/details/{product_id}"
    detalle_res = requests.get(detail_url, headers=ingram_headers())
    detalle = detalle_res.json() if detalle_res.status_code == 200 else {}
    
    product_data = {
        'id': product_id,
        'name': detalle.get('description', 'Producto sin nombre'),
        'image': get_image_url_enhanced(detalle)
    }
    
    add_to_wishlist(product_id, product_data)
    return redirect(request.referrer or url_for('catalogo_completo_cards'))

@app.route("/remove-from-wishlist/<product_id>")
def remove_from_wishlist_route(product_id):
    remove_from_wishlist(product_id)
    return redirect(url_for('view_wishlist'))

@app.route("/cart")
def view_cart():
    cart = session.get('cart', {})
    total = 0
    items = []
    
    for product_id, item in cart.items():
        item_total = float(item['data']['price']) * item['quantity']
        total += item_total
        items.append({
            'id': product_id,
            'name': item['data']['name'],
            'price': item['data']['price'],
            'currency': item['data']['currency'],
            'quantity': item['quantity'],
            'image': item['data']['image'],
            'total': item_total
        })
    
    return render_template_string('''
    <html>
    <head>
        <title>Carrito de Compras</title>
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; background: #f9f9f9; }
            .container { max-width: 1000px; margin: 0 auto; }
            .cart-item { display: flex; background: white; padding: 15px; margin-bottom: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .cart-item img { width: 100px; height: 100px; object-fit: contain; margin-right: 20px; }
            .cart-item-info { flex: 1; }
            .cart-item-actions { display: flex; align-items: center; gap: 10px; }
            .cart-total { background: white; padding: 20px; border-radius: 8px; margin-top: 20px; text-align: right; font-size: 18px; font-weight: bold; }
            .btn { padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; text-decoration: none; display: inline-block; }
            .btn-primary { background: #3498db; color: white; }
            .btn-danger { background: #e74c3c; color: white; }
            .btn-success { background: #27ae60; color: white; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Carrito de Compras</h1>
            {% if items %}
                {% for item in items %}
                <div class="cart-item">
                    <img src="{{ item.image }}" alt="{{ item.name }}">
                    <div class="cart-item-info">
                        <h3>{{ item.name }}</h3>
                        <p>Precio: {{ item.currency }} {{ item.price }}</p>
                        <p>Cantidad: {{ item.quantity }}</p>
                        <p>Total: {{ item.currency }} {{ "%.2f"|format(item.total) }}</p>
                    </div>
                    <div class="cart-item-actions">
                        <a href="/remove-from-cart/{{ item.id }}" class="btn btn-danger">Eliminar</a>
                    </div>
                </div>
                {% endfor %}
                <div class="cart-total">
                    Total: MXN {{ "%.2f"|format(total) }}
                </div>
                <div style="text-align: center; margin-top: 20px;">
                    <a href="/checkout" class="btn btn-success">Proceder al Pago</a>
                    <a href="/catalogo-completo-cards" class="btn btn-primary">Seguir Comprando</a>
                </div>
            {% else %}
                <p>Tu carrito está vacío.</p>
                <a href="/catalogo-completo-cards" class="btn btn-primary">Seguir Comprando</a>
            {% endif %}
        </div>
    </body>
    </html>
    ''', items=items, total=total)

@app.route("/wishlist")
def view_wishlist():
    wishlist = session.get('wishlist', {})
    return render_template_string('''
    <html>
    <head>
        <title>Lista de Deseos</title>
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; background: #f9f9f9; }
            .container { max-width: 1000px; margin: 0 auto; }
            .wishlist-item { display: flex; background: white; padding: 15px; margin-bottom: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .wishlist-item img { width: 100px; height: 100px; object-fit: contain; margin-right: 20px; }
            .wishlist-item-info { flex: 1; }
            .btn { padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; text-decoration: none; display: inline-block; }
            .btn-primary { background: #3498db; color: white; }
            .btn-danger { background: #e74c3c; color: white; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Lista de Deseos</h1>
            {% if wishlist %}
                {% for product_id, product in wishlist.items() %}
                <div class="wishlist-item">
                    <img src="{{ product.image }}" alt="{{ product.name }}">
                    <div class="wishlist-item-info">
                        <h3>{{ product.name }}</h3>
                    </div>
                    <div>
                        <a href="/producto/{{ product_id }}" class="btn btn-primary">Ver Producto</a>
                        <a href="/remove-from-wishlist/{{ product_id }}" class="btn btn-danger">Eliminar</a>
                    </div>
                </div>
                {% endfor %}
            {% else %}
                <p>Tu lista de deseos está vacía.</p>
            {% endif %}
            <a href="/catalogo-completo-cards" class="btn btn-primary">Seguir Comprando</a>
        </div>
    </body>
    </html>
    ''', wishlist=wishlist)

@app.route("/checkout")
def checkout():
    cart = session.get('cart', {})
    if not cart:
        return redirect(url_for('view_cart'))
    
    total = sum(float(item['data']['price']) * item['quantity'] for item in cart.values())
    
    return render_template_string('''
    <html>
    <head>
        <title>Checkout</title>
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; background: #f9f9f9; }
            .container { max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            .form-group { margin-bottom: 20px; }
            label { display: block; margin-bottom: 5px; font-weight: bold; }
            input, select { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px; }
            .btn { padding: 12px 24px; border: none; border-radius: 5px; cursor: pointer; text-decoration: none; display: inline-block; }
            .btn-success { background: #27ae60; color: white; }
            .order-summary { background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Checkout</h1>
            
            <div class="order-summary">
                <h3>Resumen del Pedido</h3>
                <p>Total: MXN {{ "%.2f"|format(total) }}</p>
            </div>
            
            <form action="/process-payment" method="POST">
                <h3>Información de Envío</h3>
                
                <div class="form-group">
                    <label>Nombre completo:</label>
                    <input type="text" name="name" required>
                </div>
                
                <div class="form-group">
                    <label>Email:</label>
                    <input type="email" name="email" required>
                </div>
                
                <div class="form-group">
                    <label>Teléfono:</label>
                    <input type="tel" name="phone" required>
                </div>
                
                <div class="form-group">
                    <label>Dirección:</label>
                    <input type="text" name="address" required>
                </div>
                
                <div class="form-group">
                    <label>Ciudad:</label>
                    <input type="text" name="city" required>
                </div>
                
                <div class="form-group">
                    <label>Código Postal:</label>
                    <input type="text" name="zipcode" required>
                </div>
                
                <h3>Información de Pago</h3>
                
                <div class="form-group">
                    <label>Número de Tarjeta:</label>
                    <input type="text" name="card_number" placeholder="1234 5678 9012 3456" required>
                </div>
                
                <div class="form-group">
                    <label>Nombre en la Tarjeta:</label>
                    <input type="text" name="card_name" required>
                </div>
                
                <div style="display: flex; gap: 15px;">
                    <div class="form-group" style="flex: 1;">
                        <label>Fecha de Expiración:</label>
                        <input type="text" name="card_expiry" placeholder="MM/AA" required>
                    </div>
                    
                    <div class="form-group" style="flex: 1;">
                        <label>CVV:</label>
                        <input type="text" name="card_cvv" placeholder="123" required>
                    </div>
                </div>
                
                <button type="submit" class="btn btn-success">Pagar Ahora</button>
            </form>
        </div>
    </body>
    </html>
    ''', total=total)

@app.route("/process-payment", methods=["POST"])
def process_payment():
    # Simular procesamiento de pago
    session.pop('cart', None)
    session['cart'] = {}
    
    return render_template_string('''
    <html>
    <head>
        <title>Pago Exitoso</title>
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; background: #f9f9f9; text-align: center; }
            .success-message { background: white; padding: 40px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); max-width: 600px; margin: 50px auto; }
            .btn { padding: 12px 24px; border: none; border-radius: 5px; cursor: pointer; text-decoration: none; display: inline-block; }
            .btn-primary { background: #3498db; color: white; }
        </style>
    </head>
    <body>
        <div class="success-message">
            <h1>¡Pago Exitoso!</h1>
            <p>Tu pedido ha sido procesado correctamente. Recibirás un email de confirmación shortly.</p>
            <p>Número de orden: #{{ "%08d"|format(range(10000000, 99999999)|random) }}</p>
            <a href="/catalogo-completo-cards" class="btn btn-primary">Seguir Comprando</a>
        </div>
    </body>
    </html>
    ''')

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
            .header-actions { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
            .action-buttons { display: flex; gap: 10px; }
            .action-btn { padding: 8px 16px; background: #3498db; color: white; text-decoration: none; border-radius: 6px; }
            .action-btn.cart { background: #27ae60; }
            .action-btn.wishlist { background: #e67e22; }
        </style>
    </head>
    <body>
        <div class="header-actions">
            <h2>Catálogo de Productos</h2>
            <div class="action-buttons">
                <a href="/cart" class="action-btn cart">🛒 Carrito ({{ session.get('cart', {})|length }})</a>
                <a href="/wishlist" class="action-btn wishlist">❤️ Favoritos ({{ session.get('wishlist', {})|length }})</a>
            </div>
        </div>
        
        {% if query or vendor %}
        <div class="search-info">
            <strong>Búsqueda activa:</strong>
            {% if query %}Texto: "{{ query }}"{% endif %}
            {% if vendor %}| Marca: "{{ vendor }}"{% endif %}
            | Búsqueda híbrida (catálogo + SKU directo + SerpApi)
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
            <div class="card">
                <a href="/producto/{{ p.get('ingramPartNumber') }}">
                    <img src="{{ get_image_url(p) }}" alt="Imagen del producto" loading="lazy">
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
                <div style="padding: 0 15px 15px 15px; display: flex; gap: 10px;">
                    <form action="/add-to-cart/{{ p.get('ingramPartNumber') }}" method="POST" style="flex: 1;">
                        <input type="hidden" name="quantity" value="1">
                        <button type="submit" style="width: 100%; padding: 8px; background: #27ae60; color: white; border: none; border-radius: 4px; cursor: pointer;">🛒 Carrito</button>
                    </form>
                    <a href="/add-to-wishlist/{{ p.get('ingramPartNumber') }}" style="padding: 8px; background: #e67e22; color: white; border-radius: 4px; text-decoration: none; display: flex; align-items: center; justify-content: center;">❤️</a>
                </div>
            </div>
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
        get_image_url=get_image_url_enhanced,
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

# ---------- DETALLE DE PRODUCTO MEJORADO ----------
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

    # Usar la función mejorada para imágenes
    imagen_url = get_image_url_enhanced(detalle)

    # Normalizar la marca para mostrar
    marca_normalizada = normalize_brand(detalle.get('vendorName', ''))

    # Render HTML con diseño mejorado
    html_template = """
    <html>
    <head>
        <title>{{ detalle.get('description', 'Detalle de Producto') }}</title>
        <meta charset="utf-8"/>
        <style>
            body { 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                padding: 20px; 
                background: #f5f7f9; 
                color: #2c3e50; 
                line-height: 1.6;
            }
            .container { 
                background: #fff; 
                padding: 25px; 
                border-radius: 12px; 
                box-shadow: 0 4px 12px rgba(0,0,0,0.1); 
                max-width: 1200px; 
                margin: 0 auto; 
            }
            .product-header {
                display: flex;
                gap: 30px;
                margin-bottom: 25px;
                align-items: flex-start;
            }
            .product-image-container {
                flex: 0 0 400px;
                background: #f8f9fa;
                border-radius: 10px;
                padding: 20px;
                border: 1px solid #e9ecef;
                text-align: center;
            }
            .product-image {
                width: 100%;
                height: 300px;
                object-fit: contain;
                border-radius: 8px;
            }
            .product-info {
                flex: 1;
            }
            .product-title {
                font-size: 28px;
                font-weight: 700;
                color: #2c3e50;
                margin: 0 0 15px 0;
                line-height: 1.3;
            }
            .product-meta {
                display: flex;
                gap: 20px;
                margin-bottom: 20px;
                flex-wrap: wrap;
            }
            .meta-item {
                background: #e8f4fd;
                padding: 10px 15px;
                border-radius: 8px;
                font-size: 14px;
            }
            .meta-item strong {
                color: #2980b9;
                display: block;
                margin-bottom: 4px;
                font-size: 12px;
                text-transform: uppercase;
            }
            .price-section {
                background: #27ae60;
                color: white;
                padding: 20px;
                border-radius: 10px;
                margin: 20px 0;
                text-align: center;
            }
            .price-label {
                font-size: 16px;
                margin-bottom: 8px;
                opacity: 0.9;
            }
            .price-amount {
                font-size: 32px;
                font-weight: 700;
                margin: 0;
            }
            .availability-section {
                background: #f39c12;
                color: white;
                padding: 15px;
                border-radius: 8px;
                margin: 20px 0;
                text-align: center;
            }
            .section {
                margin: 30px 0;
            }
            .section-title {
                font-size: 20px;
                color: #2c3e50;
                border-bottom: 2px solid #3498db;
                padding-bottom: 10px;
                margin-bottom: 15px;
            }
            .description-text {
                font-size: 16px;
                line-height: 1.6;
                color: #34495e;
            }
            .attributes-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
                gap: 15px;
                margin-top: 15px;
            }
            .attribute-item {
                background: #f8f9fa;
                padding: 15px;
                border-radius: 8px;
                border-left: 4px solid #3498db;
            }
            .attribute-name {
                font-weight: 600;
                color: #2c3e50;
                margin-bottom: 5px;
            }
            .attribute-value {
                color: #7f8c8d;
            }
            .back-btn { 
                display: inline-block; 
                padding: 12px 24px; 
                background: #3498db; 
                color: white; 
                text-decoration: none; 
                border-radius: 8px; 
                margin-bottom: 25px;
                font-weight: 600;
                transition: background 0.3s;
            }
            .back-btn:hover { 
                background: #2980b9;
            }
            .action-buttons {
                display: flex;
                gap: 15px;
                margin: 25px 0;
                flex-wrap: wrap;
            }
            .btn {
                padding: 15px 25px;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s;
                text-decoration: none;
                display: inline-flex;
                align-items: center;
                gap: 8px;
            }
            .btn-primary {
                background: #3498db;
                color: white;
            }
            .btn-primary:hover {
                background: #2980b9;
            }
            .btn-success {
                background: #27ae60;
                color: white;
            }
            .btn-success:hover {
                background: #219a52;
            }
            .btn-warning {
                background: #f39c12;
                color: white;
            }
            .btn-warning:hover {
                background: #e67e22;
            }
            .quantity-selector {
                display: flex;
                align-items: center;
                gap: 10px;
                margin: 15px 0;
            }
            .quantity-selector input {
                width: 70px;
                padding: 10px;
                border: 1px solid #ddd;
                border-radius: 5px;
                text-align: center;
            }
            @media (max-width: 900px) {
                .product-header {
                    flex-direction: column;
                }
                .product-image-container {
                    flex: none;
                    width: 100%;
                    max-width: 400px;
                    margin: 0 auto;
                }
                .action-buttons {
                    flex-direction: column;
                }
                .btn {
                    width: 100%;
                    justify-content: center;
                }
            }
        </style>
    </head>
    <body>
        <a href="/catalogo-completo-cards" class="back-btn">⬅ Volver al catálogo</a>
        
        <div class="container">
            <div class="product-header">
                <div class="product-image-container">
                    <img src="{{ imagen_url }}" alt="Imagen del producto" class="product-image">
                </div>
                
                <div class="product-info">
                    <h1 class="product-title">{{ detalle.get('description', 'Sin descripción') }}</h1>
                    
                    <div class="product-meta">
                        <div class="meta-item">
                            <strong>SKU Ingram</strong>
                            {{ detalle.get('ingramPartNumber') or part_number }}
                        </div>
                        <div class="meta-item">
                            <strong>Marca</strong>
                            {{ marca_normalizada or 'No disponible' }}
                        </div>
                        <div class="meta-item">
                            <strong>Categoría</strong>
                            {{ detalle.get('category', 'Electrónica') }}
                        </div>
                    </div>

                    <div class="price-section">
                        <div class="price-label">Precio especial</div>
                        <div class="price-amount">{{ precio_final }}</div>
                    </div>

                    <div class="availability-section">
                        <strong>Disponibilidad:</strong> {{ disponibilidad }}
                    </div>

                    <!-- Botones de acción -->
                    <div class="action-buttons">
                        <form action="/add-to-cart/{{ part_number }}" method="POST" style="display: flex; gap: 15px; align-items: center;">
                            <div class="quantity-selector">
                                <label for="quantity">Cantidad:</label>
                                <input type="number" id="quantity" name="quantity" value="1" min="1" max="10">
                            </div>
                            <button type="submit" class="btn btn-success">
                                🛒 Añadir al Carrito
                            </button>
                        </form>
                        
                        <a href="/add-to-wishlist/{{ part_number }}" class="btn btn-warning">
                            ❤️ Añadir a Favoritos
                        </a>
                        
                        <form action="/add-to-cart/{{ part_number }}" method="POST">
                            <input type="hidden" name="quantity" value="1">
                            <button type="submit" class="btn btn-primary">
                                ⚡ Comprar Ahora
                            </button>
                        </form>
                    </div>
                </div>
            </div>

            <div class="section">
                <h2 class="section-title">Descripción del Producto</h2>
                <p class="description-text">{{ descripcion_larga }}</p>
            </div>

            {% if atributos %}
            <div class="section">
                <h2 class="section-title">Características Técnicas</h2>
                <div class="attributes-grid">
                    {% for a in atributos %}
                    <div class="attribute-item">
                        <div class="attribute-name">{{ a.name }}</div>
                        <div class="attribute-value">{{ a.value }}</div>
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endif %}

            <div class="section">
                <h2 class="section-title">Información Adicional</h2>
                <div class="attributes-grid">
                    <div class="attribute-item">
                        <div class="attribute-name">Número de Parte</div>
                        <div class="attribute-value">{{ detalle.get('ingramPartNumber') or part_number }}</div>
                    </div>
                    <div class="attribute-item">
                        <div class="attribute-name">Marca</div>
                        <div class="attribute-value">{{ marca_normalizada or 'No disponible' }}</div>
                    </div>
                    <div class="attribute-item">
                        <div class="attribute-name">Categoría</div>
                        <div class="attribute-value">{{ detalle.get('category', 'Electrónica') }}</div>
                    </div>
                    <div class="attribute-item">
                        <div class="attribute-name">Subcategoría</div>
                        <div class="attribute-value">{{ detalle.get('subCategory', 'Accesorios') }}</div>
                    </div>
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
        part_number=part_number,
        marca_normalizada=marca_normalizada
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)