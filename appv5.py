import os
import time
import uuid
import requests
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Credenciales de API (poner en .env)
CLIENT_ID = os.getenv("INGRAM_CLIENT_ID")
CLIENT_SECRET = os.getenv("INGRAM_CLIENT_SECRET")

# Token global
TOKEN = None
TOKEN_EXPIRY = 0

# Cache para búsquedas
search_cache = {}
CACHE_EXPIRY_HOURS = 24

# Función para guardar en caché
def save_to_cache(key, data):
    search_cache[key] = {
        'data': data,
        'expiry': datetime.now() + timedelta(hours=CACHE_EXPIRY_HOURS)
    }

# Función para recuperar del caché
def get_from_cache(key):
    if key in search_cache:
        if datetime.now() < search_cache[key]['expiry']:
            return search_cache[key]['data']
        else:
            del search_cache[key]  # Eliminar entrada expirada
    return None

# Función para obtener marcas disponibles localmente
def get_local_vendors():
    # Lista de marcas comunes en tecnología
    common_vendors = [
        "HP Cómputo", "Dell", "Lenovo", "Cisco", "Apple", "Microsoft", "Adata", "Getttech", "Acteck", "Hpe Accs", "Yeyian",
        "Samsung", "LG", "ASUS", "Acer", "Vorago", "Cnp T5 Enterprise", "NACEB", "Cecotec", "Barco", "Vorago Accs","Sansui",
        "Intel", "AMD", "Meraki", "Logitech", "Kingston", "Seagate", "Manhattan", "Kensington", "Toshiba (Pp)", "CyberPower",
        "Elo Touch", "TP-Link", "Zebra Tech.", "Jabra", "Poly", "LG Digital Signage", "Compulocks", "APC", "Balam Rush", "InFocus",
        "Canon", "Epson", "Brother", "StarTech.com", "HP POLY", "Honeywell", "Qian", "Intellinet", "BRobotix", "Eaton Consig Cables",
        "Xerox", "Perfect Choice", "Buffalo", "Hisense", "Dell NPOS", "HP Impresión", "Xzeal Gaming", "CDP", "Zebra Printers",
        "Targus", "Avision", "HPE ARUBA NETWORKING", "Cnp Meraki", "Zebra", "Vica", "Eaton", "Smartbitt", "BenQ", "Lenovo Idea Nb",
        "Hewlett Packard Enterprise", "Lenovo DCG", "Eaton Proyectos", "Eaton Consig Kvm", "Epson Hw", "Lexmark", "Axis", "TechZone",
        "Bixolon", "IBM", "Screenbeam", "Tecnosinergia", "TechZone DC POS", "Uniarch By Unv", "Lenovo Global", "Impresoras Zebra",
        "Surface", "Vertiv", "TMCELL", "Zebra Lectores", "Star Micronics", "Peerless", "Infinix Mobility", "Pdp", "Zebra Adc A5, A6", 
        "Corsair (Arroba)", "QNAP", "Chicago Digital", "Viewsonic", "KINGSTON PP FLASH", "Hp Componentes", "Silimex", "XPG", "Dell Memory",
        "Kvr Ar", "3M", "Dataproducts", "Hid Global", "Msi Componentes", "Cooler Master (A)", "Msi Componentes (A)", "Corsair", "Lacie",
        "Unitech America", "Ezviz", "Ingressio", "Sharp",
    ]
    return sorted(common_vendors)

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
            return None

        available_flag = av.get("available")
        # si hay al menos unidades o flag true -> disponible
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


# Cache para imágenes (evitar llamadas repetidas)
image_cache = {}

def get_image_url_enhanced(item):
    """
    Función optimizada que usa información específica del producto para buscar imágenes.
    Prioridad: Ingram -> Cache -> Categoría -> Unsplash -> Placeholder personalizado
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
    
    # 2. Verificar cache para evitar llamadas repetidas
    sku = item.get("ingramPartNumber", "")
    vendor_part = item.get("vendorPartNumber", "")
    
    # Usar vendorPartNumber si está disponible (más específico)
    cache_key = vendor_part if vendor_part else sku
    if cache_key in image_cache:
        return image_cache[cache_key]
    
    # 3. Buscar por categoría y subcategoría de producto
    category_image = get_category_based_image(item)
    if category_image:
        if cache_key:
            image_cache[cache_key] = category_image
        return category_image
    
    # 4. Buscar con Unsplash API usando información específica del producto
    producto_nombre = item.get("description", "")
    marca = item.get("vendorName", "")
    categoria = item.get("category", "")
    subcategoria = item.get("subCategory", "")
    
    # Construir query usando información específica
    search_query = build_unsplash_query(marca, producto_nombre, sku, vendor_part, categoria, subcategoria)
    unsplash_image = get_unsplash_image(search_query)
    
    if unsplash_image:
        if cache_key:
            image_cache[cache_key] = unsplash_image
        return unsplash_image
    
    # 5. Fallback con placeholder personalizado
    placeholder = generate_custom_placeholder(marca, producto_nombre, sku, vendor_part)
    if cache_key:
        image_cache[cache_key] = placeholder
    return placeholder


def build_unsplash_query(marca, producto_nombre, sku, vendor_part, categoria, subcategoria):
    """Construye query optimizada para Unsplash usando información específica del producto"""
    
    # Prioridad 1: Vendor Part Number (más específico)
    if vendor_part and len(vendor_part) > 3:
        return f"{marca} {vendor_part} {producto_nombre.split()[0] if producto_nombre else ''}"
    
    # Prioridad 2: SKU + Marca
    if sku and marca:
        return f"{marca} {sku}"
    
    # Prioridad 3: Categoría y subcategoría específicas
    if categoria and subcategoria:
        return f"{marca} {categoria} {subcategoria} {producto_nombre.split()[0] if producto_nombre else ''}"
    
    # Prioridad 4: Nombre del producto con marca
    if marca and producto_nombre:
        # Limpiar y optimizar nombre (solo 2-3 palabras clave)
        nombre_limpio = " ".join(producto_nombre.replace(",", "").replace("-", " ").split()[:3])
        return f"{marca} {nombre_limpio}"
    
    # Prioridad 5: Solo SKU
    if sku:
        return f"{sku}"
    
    # Fallback: categoría general
    return f"{categoria} {subcategoria}"


def get_unsplash_image(search_query):
    """
    Busca imágenes en Unsplash API con queries optimizadas para productos tecnológicos
    """
    api_key = os.getenv("UNSPLASH_ACCESS_KEY")
    if not api_key:
        return None
    
    try:
        url = "https://api.unsplash.com/search/photos"
        
        # Queries progresivas de más específica a más genérica
        queries_to_try = [
            f"{search_query} technology product",
            f"{search_query} tech device",
            f"{search_query} computer",
            search_query,
            "technology product"  # fallback final
        ]
        
        for query in queries_to_try:
            params = {
                "query": query,
                "per_page": 5,
                "orientation": "squarish",
                "content_filter": "high",
                "order_by": "relevant"
            }
            headers = {
                "Authorization": f"Client-ID {api_key}",
                "Accept-Version": "v1"
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=6)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                
                for result in results:
                    urls = result.get("urls", {})
                    # Preferir 'regular' (1080px) para buen balance calidad/velocidad
                    image_url = urls.get("regular") or urls.get("small") or urls.get("thumb")
                    if image_url:
                        return image_url
                
                # Si encontramos resultados pero ninguno válido, intentar siguiente query
                continue
            
            # Manejar rate limits
            elif response.status_code == 403:
                print("Unsplash API rate limit alcanzado")
                break
        
    except Exception as e:
        print(f"Error con Unsplash API: {e}")
    
    return None


def get_category_based_image(item):
    """
    Mapea productos a imágenes de alta calidad por categoría
    Usa información específica de category y subCategory
    """
    descripcion = item.get("description", "").lower()
    marca = item.get("vendorName", "").lower()
    categoria = item.get("category", "").lower()
    subcategoria = item.get("subCategory", "").lower()
    
    # Mapeo optimizado con imágenes Unsplash de alta calidad
    category_mapping = {
        # Laptops y notebooks
        ("laptop", "notebook", "elitebook", "thinkpad", "macbook", "ultrabook"): 
            "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?w=400&h=400&fit=crop&auto=format&q=80",
        
        # Computadoras de escritorio
        ("desktop", "workstation", "pc", "tower", "all-in-one"): 
            "https://images.unsplash.com/photo-1587831990711-23ca6441447b?w=400&h=400&fit=crop&auto=format&q=80",
        
        # Monitores y pantallas
        ("monitor", "display", "screen", "lcd", "led", "oled", "curved"): 
            "https://images.unsplash.com/photo-1527443224154-c4a3942d3acf?w=400&h=400&fit=crop&auto=format&q=80",
        
        # Impresoras
        ("printer", "impresora", "laserjet", "inkjet", "multifunc"): 
            "https://images.unsplash.com/photo-1612815154858-60aa4c59eaa6?w=400&h=400&fit=crop&auto=format&q=80",
        
        # Networking y conectividad
        ("router", "switch", "firewall", "access point", "wifi", "ethernet"): 
            "https://images.unsplash.com/photo-1544197150-b99a580bb7a8?w=400&h=400&fit=crop&auto=format&q=80",
        
        # Servidores y datacenter
        ("server", "servidor", "rack", "blade", "datacenter"): 
            "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?w=400&h=400&fit=crop&auto=format&q=80",
        
        # Almacenamiento
        ("storage", "disk", "ssd", "hdd", "nas", "san", "drive"): 
            "https://images.unsplash.com/photo-1597852074816-d933c7d2b988?w=400&h=400&fit=crop&auto=format&q=80",
        
        # Tablets
        ("tablet", "ipad", "surface", "android tablet"): 
            "https://images.unsplash.com/photo-1544244015-0df4b3ffc6b0?w=400&h=400&fit=crop&auto=format&q=80",
        
        # Smartphones
        ("smartphone", "phone", "iphone", "android", "mobile"): 
            "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=400&h=400&fit=crop&auto=format&q=80",
        
        # Cámaras
        ("camera", "webcam", "camara", "video"): 
            "https://images.unsplash.com/photo-1606983340126-99ab4feaa64a?w=400&h=400&fit=crop&auto=format&q=80",
        
        # Audio (incluye headsets como el ejemplo Jabra)
        ("audio", "headset", "headphone", "auricular", "microphone", "speaker", "música"): 
            "https://images.unsplash.com/photo-1545454675-3531b543be5d?w=400&h=400&fit=crop&auto=format&q=80",
        
        # Accesorios y cables
        ("cable", "adapter", "adaptador", "charger", "cargador", "hub"): 
            "https://images.unsplash.com/photo-1625842268584-8f3296236761?w=400&h=400&fit=crop&auto=format&q=80",
        
        # Periféricos
        ("keyboard", "mouse", "teclado", "raton", "trackpad"): 
            "https://images.unsplash.com/photo-1541140532154-b024d705b90a?w=400&h=400&fit=crop&auto=format&q=80",
        
        # Software y licencias
        ("software", "license", "licencia", "windows", "office", "antivirus"): 
            "https://images.unsplash.com/photo-1515879218367-8466d910aaa4?w=400&h=400&fit=crop&auto=format&q=80",
        
        # Componentes internos
        ("memory", "ram", "processor", "cpu", "gpu", "motherboard"): 
            "https://images.unsplash.com/photo-1591799264318-7e6ef8ddb7ea?w=400&h=400&fit=crop&auto=format&q=80",
        
        # Gaming
        ("gaming", "gamer", "game", "xbox", "playstation"): 
            "https://images.unsplash.com/photo-1552820728-8b83bb6b773f?w=400&h=400&fit=crop&auto=format&q=80",
    }
    
    # Buscar coincidencias en descripción, marca, categoría y subcategoría
    text_to_search = f"{descripcion} {marca} {categoria} {subcategoria}".lower()
    
    for keywords, image_url in category_mapping.items():
        if any(keyword in text_to_search for keyword in keywords):
            return image_url
    
    return None


def generate_custom_placeholder(marca, producto_nombre, sku, vendor_part):
    """
    Genera placeholders personalizados y atractivos usando información específica
    """
    try:
        from urllib.parse import quote_plus
        
        # Determinar texto y color basado en la información disponible
        if vendor_part and len(vendor_part) <= 20:
            text = f"P/N: {vendor_part}"
            color = "F15A29"  # Naranja corporativo
        elif marca and len(marca) <= 20:
            text = marca.upper()
            # Colores por marca conocida usando la paleta corporativa
            brand_colors = {
                "HP": "1C2A2F",
                "DELL": "1C2A2F", 
                "CISCO": "1C2A2F",
                "APPLE": "1C2A2F",
                "LENOVO": "F15A29",
                "MICROSOFT": "1C2A2F",
                "INTEL": "1C2A2F",
                "AMD": "F15A29",
                "JABRA": "1C2A2F"
            }
            color = brand_colors.get(marca.upper(), "6C757D")  # Gris medio como fallback
        elif sku and len(sku) <= 20:
            text = f"SKU: {sku}"
            color = "F15A29"  # Naranja corporativo
        elif producto_nombre:
            # Crear texto descriptivo corto
            words = producto_nombre.replace(",", "").split()[:3]
            text = " ".join(words).upper()
            if len(text) > 25:
                text = text[:25] + "..."
            color = "6C757D"  # Gris medio
        else:
            text = "IT DATA GLOBAL"
            color = "1C2A2F"  # Negro azulado oscuro
        
        encoded_text = quote_plus(text)
        return f"https://via.placeholder.com/400x400/{color}/FFFFFF?text={encoded_text}&font_size=16"
        
    except Exception:
        return "https://via.placeholder.com/400x400/1C2A2F/FFFFFF?text=IT+DATA+GLOBAL"


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

def buscar_productos_hibrido(query="", vendor="", page_number=1, page_size=25):
    """
    Búsqueda híbrida que prioriza el caché local y solo usa API para SKUs específicos.
    """
    # Generar clave única para esta búsqueda
    cache_key = f"{query}_{vendor}_{page_number}_{page_size}"
    
    # Intentar obtener del caché primero
    cached_result = get_from_cache(cache_key)
    if cached_result:
        return cached_result['productos'], cached_result['total_records'], cached_result['pagina_vacia']
    
    productos_finales = []
    total_records = 0
    pagina_vacia = False
    
    # 1. Si la query parece un SKU específico, usar API
    if query and len(query.strip()) < 30 and len(query.strip().split()) <= 3:
        productos_sku = buscar_por_sku_directo(query.strip())
        if productos_sku:
            productos_finales.extend(productos_sku)
            total_records += len(productos_sku)
    
    # 2. Para búsquedas generales, usar caché o API como último recurso
    if not productos_finales and (query or vendor):
        productos_catalogo, records_catalogo, pagina_vacia = buscar_en_catalogo_general(query, vendor, page_number, page_size)
        
        # Evitar duplicados
        skus_existentes = {p.get('ingramPartNumber') for p in productos_finales if p.get('ingramPartNumber')}
        for producto in productos_catalogo:
            if producto.get('ingramPartNumber') not in skus_existentes:
                productos_finales.append(producto)
        
        total_records += records_catalogo
    
    # Guardar en caché para futuras consultas
    if query or vendor:  # Solo cachear búsquedas específicas, no el catálogo completo
        save_to_cache(cache_key, {
            'productos': productos_finales,
            'total_records': total_records,
            'pagina_vacia': pagina_vacia
        })
    
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
                            "vendorPartNumber": detalle.get("vendorPartNumber"),
                            "description": (detalle.get("description") or 
                                          producto_info.get("description") or 
                                          "Descripción no disponible"),
                            "vendorName": (detalle.get("vendorName") or 
                                         producto_info.get("vendorName") or 
                                         "Marca no disponible"),
                            "category": detalle.get("category"),
                            "subCategory": detalle.get("subCategory"),
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
    if vendor and vendor != "Todas las marcas":
        params["vendor"] = vendor
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
    
    # Si es la primera carga sin parámetros, mostrar mensaje de bienvenida
    if not query and not vendor and page_number == 1:
        productos, total_records, pagina_vacia = [], 0, False
        welcome_message = True
    else:
        # Usar búsqueda híbrida
        productos, total_records, pagina_vacia = buscar_productos_hibrido(query, vendor, page_number, page_size)
        welcome_message = False
    
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
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>IT Data Global - Catálogo de Productos</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                background: #F1F3F4;
                min-height: 100vh;
                color: #1C2A2F;
            }

            /* Header Profesional con nueva paleta */
            .header {
                background: #1C2A2F;
                color: #FFFFFF;
                padding: 1rem 0;
                box-shadow: 0 4px 20px rgba(28, 42, 47, 0.3);
                position: sticky;
                top: 0;
                z-index: 100;
                border-bottom: 3px solid #F15A29;
            }

            .header-content {
                max-width: 1400px;
                margin: 0 auto;
                padding: 0 2rem;
                display: flex;
                align-items: center;
                justify-content: space-between;
            }

            .logo {
                font-size: 2rem;
                font-weight: 700;
                text-decoration: none;
                color: #FFFFFF;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .logo i {
                color: #F15A29;
            }

            .header-stats {
                display: flex;
                gap: 2rem;
                font-size: 0.9rem;
                opacity: 0.9;
            }

            .stat-item {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                color: #FFFFFF;
            }

            /* Container Principal */
            .main-container {
                max-width: 1400px;
                margin: 2rem auto;
                padding: 0 2rem;
            }

            /* Breadcrumb */
            .breadcrumb {
                background: #FFFFFF;
                padding: 1rem 1.5rem;
                border-radius: 16px;
                margin-bottom: 2rem;
                box-shadow: 0 4px 20px rgba(28, 42, 47, 0.08);
                border-left: 4px solid #F15A29;
            }

            .breadcrumb-list {
                display: flex;
                align-items: center;
                list-style: none;
                gap: 0.5rem;
                color: #6C757D;
                font-size: 0.9rem;
            }

            .breadcrumb-list a {
                color: #F15A29;
                text-decoration: none;
            }

            .breadcrumb-list a:hover {
                text-decoration: underline;
            }

            /* Información de búsqueda mejorada */
            .search-info {
                background: linear-gradient(135deg, #F15A29 0%, #FF7F50 100%);
                color: white;
                padding: 1.5rem;
                border-radius: 16px;
                margin-bottom: 2rem;
                box-shadow: 0 8px 32px rgba(241, 90, 41, 0.3);
                position: relative;
                overflow: hidden;
            }

            .search-info::before {
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="20" cy="20" r="2" fill="white" opacity="0.1"/><circle cx="80" cy="80" r="3" fill="white" opacity="0.1"/><circle cx="40" cy="70" r="1" fill="white" opacity="0.1"/></svg>');
                pointer-events: none;
            }

            .search-info-content {
                position: relative;
                z-index: 1;
            }

            /* Barra de búsqueda profesional */
            .search-container {
                background: white;
                border-radius: 20px;
                padding: 2rem;
                margin-bottom: 2rem;
                box-shadow: 0 10px 40px rgba(28, 42, 47, 0.1);
            }

            .search-form {
                display: grid;
                grid-template-columns: 1fr 1fr auto auto;
                gap: 1rem;
                align-items: end;
            }

            .form-group {
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
            }

            .form-label {
                font-weight: 600;
                color: #1C2A2F;
                font-size: 0.9rem;
            }

            .form-input {
                padding: 1rem 1.5rem;
                border: 2px solid #DEE2E6;
                border-radius: 12px;
                font-size: 1rem;
                transition: all 0.3s ease;
                background: #FFFFFF;
            }

            .form-input:focus {
                outline: none;
                border-color: #F15A29;
                background: white;
                box-shadow: 0 0 0 3px rgba(241, 90, 41, 0.1);
            }

            .btn {
                padding: 1rem 2rem;
                border: none;
                border-radius: 12px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s ease;
                text-decoration: none;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 0.5rem;
                font-size: 1rem;
                white-space: nowrap;
            }

            .btn-primary {
                background: #F15A29;
                color: white;
            }

            .btn-primary:hover {
                background: #d14a1f;
                transform: translateY(-2px);
                box-shadow: 0 8px 25px rgba(241, 90, 41, 0.3);
            }

            .btn-secondary {
                background: #FFFFFF;
                color: #6C757D;
                border: 2px solid #DEE2E6;
            }

            .btn-secondary:hover {
                background: #F1F3F4;
                border-color: #1C2A2F;
            }

            /* Resultados y paginación info */
            .results-info {
                background: white;
                padding: 1.5rem;
                border-radius: 16px;
                margin-bottom: 2rem;
                box-shadow: 0 4px 20px rgba(28, 42, 47, 0.06);
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-left: 4px solid #F15A29;
            }

            .results-text {
                font-weight: 600;
                color: #1C2A2F;
            }

            .page-info {
                color: #6C757D;
                font-size: 0.9rem;
            }

            /* Grid de productos mejorado */
            .products-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
                gap: 2rem;
                margin-bottom: 3rem;
            }

            /* Tarjetas de producto premium */
            .product-card {
                background: white;
                border-radius: 20px;
                overflow: hidden;
                text-decoration: none;
                color: inherit;
                transition: all 0.4s cubic-bezier(0.165, 0.84, 0.44, 1);
                box-shadow: 0 8px 30px rgba(28, 42, 47, 0.08);
                position: relative;
                border: 1px solid #F1F3F4;
            }

            .product-card:hover {
                transform: translateY(-8px);
                box-shadow: 0 20px 60px rgba(28, 42, 47, 0.15);
                border-color: #F15A29;
            }

            .product-image-container {
                position: relative;
                height: 280px;
                background: #F1F3F4;
                overflow: hidden;
            }

            .product-image {
                width: 100%;
                height: 100%;
                object-fit: contain;
                transition: transform 0.4s ease;
                padding: 1rem;
            }

            .product-card:hover .product-image {
                transform: scale(1.05);
            }

            .product-badge {
                position: absolute;
                top: 1rem;
                right: 1rem;
                background: #F15A29;
                color: white;
                padding: 0.5rem 1rem;
                border-radius: 20px;
                font-size: 0.8rem;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }

            .product-content {
                padding: 2rem;
            }

            .product-brand {
                color: #F15A29;
                font-size: 0.9rem;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                margin-bottom: 0.5rem;
            }

            .product-title {
                font-size: 1.1rem;
                font-weight: 600;
                color: #1C2A2F;
                margin-bottom: 1rem;
                line-height: 1.4;
                height: 3.2em;
                overflow: hidden;
                display: -webkit-box;
                -webkit-line-clamp: 2;
                -webkit-box-orient: vertical;
            }

            .product-sku {
                font-family: 'Monaco', 'Menlo', monospace;
                background: #F1F3F4;
                padding: 0.5rem 1rem;
                border-radius: 10px;
                font-size: 0.85rem;
                color: #6C757D;
                margin-bottom: 1rem;
                font-weight: 500;
                border-left: 4px solid #F15A29;
            }

            .product-details {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-top: 1.5rem;
                padding-top: 1.5rem;
                border-top: 1px solid #F1F3F4;
            }

            .product-price {
                font-size: 1.4rem;
                font-weight: 700;
                color: #F15A29;
            }

            .product-availability {
                font-size: 0.9rem;
                padding: 0.4rem 0.8rem;
                border-radius: 12px;
                font-weight: 500;
            }

            .availability-available {
                background: #d4edda;
                color: #155724;
                border: 2px solid #c3e6cb;
            }

            .availability-limited {
                background: #fff3cd;
                color: #856404;
                border: 2px solid #ffeaa7;
            }

            .availability-out {
                background: #f8d7da;
                color: #721c24;
                border: 2px solid #f5c6cb;
            }

            /* Estados de la página */
            .empty-state {
                text-align: center;
                padding: 4rem 2rem;
                background: white;
                border-radius: 20px;
                box-shadow: 0 8px 30px rgba(28, 42, 47, 0.08);
                margin: 2rem 0;
                border-left: 4px solid #F15A29;
            }

            .empty-state-icon {
                font-size: 4rem;
                color: #DEE2E6;
                margin-bottom: 1.5rem;
            }

            .empty-state-title {
                font-size: 1.5rem;
                font-weight: 600;
                color: #1C2A2F;
                margin-bottom: 1rem;
            }

            .empty-state-description {
                color: #6C757D;
                margin-bottom: 2rem;
                line-height: 1.6;
            }

            .empty-state-suggestions {
                background: #F1F3F4;
                padding: 1.5rem;
                border-radius: 12px;
                margin: 1.5rem 0;
                text-align: left;
                max-width: 500px;
                margin-left: auto;
                margin-right: auto;
            }

            .empty-state-suggestions h4 {
                color: #1C2A2F;
                margin-bottom: 1rem;
                font-weight: 600;
            }

            .empty-state-suggestions ul {
                list-style: none;
                color: #6C757D;
            }

            .empty-state-suggestions li {
                padding: 0.5rem 0;
                padding-left: 1.5rem;
                position: relative;
            }

            .empty-state-suggestions li:before {
                content: '💡';
                position: absolute;
                left: 0;
                color: #F15A29;
            }

            /* Paginación profesional */
            .pagination-container {
                background: white;
                padding: 2rem;
                border-radius: 20px;
                box-shadow: 0 8px 30px rgba(28, 42, 47, 0.08);
                text-align: center;
                border-left: 4px solid #F15A29;
            }

            .pagination {
                display: flex;
                justify-content: center;
                align-items: center;
                gap: 1rem;
                margin-bottom: 1.5rem;
            }

            .pagination-btn {
                padding: 0.8rem 1.5rem;
                border: 2px solid #DEE2E6;
                background: white;
                color: #6C757D;
                border-radius: 12px;
                text-decoration: none;
                font-weight: 500;
                transition: all 0.3s ease;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .pagination-btn:hover:not(.disabled) {
                border-color: #F15A29;
                color: #F15A29;
                transform: translateY(-2px);
                box-shadow: 0 4px 15px rgba(241, 90, 41, 0.2);
            }

            .pagination-btn.disabled {
                background: #F1F3F4;
                color: #DEE2E6;
                cursor: not-allowed;
                border-color: #F1F3F4;
            }

            .page-jump {
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 1rem;
                padding: 1.5rem;
                background: #F1F3F4;
                border-radius: 16px;
                margin-top: 1rem;
            }

            .page-jump input {
                width: 80px;
                padding: 0.6rem;
                border: 2px solid #DEE2E6;
                border-radius: 8px;
                text-align: center;
                font-weight: 600;
            }

            .page-jump input:focus {
                outline: none;
                border-color: #F15A29;
                box-shadow: 0 0 0 3px rgba(241, 90, 41, 0.1);
            }

            /* Responsive Design */
            @media (max-width: 768px) {
                .header-content {
                    flex-direction: column;
                    gap: 1rem;
                    text-align: center;
                }

                .header-stats {
                    justify-content: center;
                }

                .search-form {
                    grid-template-columns: 1fr;
                    gap: 1rem;
                }

                .products-grid {
                    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                    gap: 1.5rem;
                }

                .results-info {
                    flex-direction: column;
                    gap: 1rem;
                    text-align: center;
                }

                .pagination {
                    flex-direction: column;
                    gap: 1rem;
                }

                .main-container {
                    padding: 0 1rem;
                }
            }

            /* Animaciones sutiles */
            @keyframes fadeInUp {
                from {
                    opacity: 0;
                    transform: translateY(30px);
                }
                to {
                    opacity: 1;
                    transform: translateY(0);
                }
            }

            .product-card {
                animation: fadeInUp 0.6s ease forwards;
            }

            .product-card:nth-child(2) { animation-delay: 0.1s; }
            .product-card:nth-child(3) { animation-delay: 0.2s; }
            .product-card:nth-child(4) { animation-delay: 0.3s; }

            /* Loading states */
            .loading-shimmer {
                background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
                background-size: 200% 100%;
                animation: shimmer 1.5s infinite;
            }

            @keyframes shimmer {
                0% { background-position: -200% 0; }
                100% { background-position: 200% 0; }
            }
        </style>
    </head>
    <body>
        <!-- Header Profesional -->
        <header class="header">
            <div class="header-content">
                <a href="/catalogo-completo-cards" class="logo">
                    <i class="fas fa-microchip"></i>
                    IT Data Global
                </a>
                <div class="header-stats">
                    <div class="stat-item">
                        <i class="fas fa-boxes"></i>
                        <span>{{ total_records }}+ productos</span>
                    </div>
                    <div class="stat-item">
                        <i class="fas fa-shipping-fast"></i>
                        <span>Envío rápido</span>
                    </div>
                    <div class="stat-item">
                        <i class="fas fa-shield-alt"></i>
                        <span>Garantía oficial</span>
                    </div>
                </div>
            </div>
        </header>

        <!-- Container Principal -->
        <div class="main-container">
            <!-- Breadcrumb -->
            <nav class="breadcrumb">
                <ul class="breadcrumb-list">
                    <li><i class="fas fa-home"></i></li>
                    <li><i class="fas fa-chevron-right"></i></li>
                    <li>Catálogo</li>
                    {% if query or vendor %}
                    <li><i class="fas fa-chevron-right"></i></li>
                    <li>Búsqueda</li>
                    {% endif %}
                </ul>
            </nav>

            {% if query or vendor %}
            <div class="search-info">
                <div class="search-info-content">
                    <h3 style="margin-bottom: 0.5rem; font-weight: 600;">
                        <i class="fas fa-search" style="margin-right: 0.5rem;"></i>
                        Búsqueda Activa
                    </h3>
                    <p style="opacity: 0.9;">
                        {% if query %}Texto: "<strong>{{ query }}</strong>"{% endif %}
                        {% if vendor %} | Marca: "<strong>{{ vendor }}</strong>"{% endif %}
                        | Sistema híbrido (catálogo + búsqueda directa)
                    </p>
                </div>
            </div>
            {% endif %}

            <!-- Barra de búsqueda profesional -->
            <div class="search-container">
                <form method="get" class="search-form">
                    <div class="form-group">
                        <label class="form-label">
                            <i class="fas fa-search"></i> Buscar productos
                        </label>
                        <input type="text" name="q" class="form-input" 
                               placeholder="Nombre, descripción, SKU o número de parte..." 
                               value="{{ query }}">
                    </div>
                    <div class="form-group">
                        <label class="form-label">
                            <i class="fas fa-tags"></i> Filtrar por marca
                        </label>
                        <select name="vendor" class="form-input">
                            <option value="">Todas las marcas</option>
                            {% for v in local_vendors %}
                                <option value="{{ v }}" {% if v == vendor %}selected{% endif %}>
                                    {{ v }}
                                </option>
                            {% endfor %}
                        </select>
                    </div>
                    <button type="submit" class="btn btn-primary">
                        <i class="fas fa-search"></i>
                        Buscar
                    </button>
                    <a href="/catalogo-completo-cards" class="btn btn-secondary">
                        <i class="fas fa-eraser"></i>
                        Limpiar
                    </a>
                </form>
            </div>

            <!-- Información de resultados -->
            <div class="results-info">
                <div class="results-text">
                    <strong>{{ start_record }} - {{ end_record }}</strong> de <strong>{{ total_records }}</strong> productos encontrados
                </div>
                <div class="page-info">
                    Página {{ page_number }} de {{ total_pages }}
                </div>
            </div>

            {% if welcome_message %}
            <div class="empty-state">
                <div class="empty-state-icon">
                    <i class="fas fa-search"></i>
                </div>
                <h3 class="empty-state-title">Bienvenido al Catálogo IT Data Global</h3>
                <p class="empty-state-description">
                    Utiliza el formulario de búsqueda para encontrar productos específicos o selecciona una marca para filtrar.
                </p>
                <div class="empty-state-suggestions">
                    <h4>Puedes buscar por:</h4>
                    <ul>
                        <li>Nombre del producto</li>
                        <li>Número de parte (SKU)</li>
                        <li>Número de parte del fabricante</li>
                        <li>Marca específica</li>
                    </ul>
                </div>
            </div>
            {% elif pagina_vacia and page_number > 1 %}
            <div class="empty-state">
                <div class="empty-state-icon">
                    <i class="fas fa-file-alt"></i>
                </div>
                <h3 class="empty-state-title">Página sin resultados</h3>
                <p class="empty-state-description">
                    No hay más productos disponibles en esta página. La API tiene limitaciones de paginación.
                </p>
                <a href="?page=1&q={{ query }}&vendor={{ vendor }}" class="btn btn-primary">
                    <i class="fas fa-arrow-left"></i>
                    Volver a la página 1
                </a>
            </div>
            {% elif not productos and not welcome_message %}
            <div class="empty-state">
                <div class="empty-state-icon">
                    <i class="fas fa-search"></i>
                </div>
                <h3 class="empty-state-title">Sin resultados</h3>
                <p class="empty-state-description">
                    No se encontraron productos que coincidan con tu búsqueda.
                </p>
                <div class="empty-state-suggestions">
                    <h4>Sugerencias para mejorar tu búsqueda:</h4>
                    <ul>
                        <li>Verifica la ortografía de los términos</li>
                        <li>Intenta con términos más generales</li>
                        <li>Busca por marca específica (HP, Dell, Cisco)</li>
                        <li>Prueba con el número de parte exacto</li>
                        <li>Usa menos palabras en tu búsqueda</li>
                    </ul>
                </div>
                <a href="/catalogo-completo-cards" class="btn btn-primary">
                    <i class="fas fa-home"></i>
                    Ver catálogo completo
                </a>
            </div>
            {% else %}
            
            <!-- Grid de productos -->
            <div class="products-grid">
                {% for p in productos %}
                <a class="product-card" href="/producto/{{ p.get('ingramPartNumber') }}">
                    <div class="product-image-container">
                        <img src="{{ get_image_url_enhanced(p) }}" alt="{{ p.get('description', 'Producto') }}" class="product-image" loading="lazy">
                        {% if p.get('availability') %}
                        <div class="product-badge">
                            <i class="fas fa-check"></i> Disponible
                        </div>
                        {% endif %}
                    </div>
                    <div class="product-content">
                        <div class="product-brand">{{ p.get('vendorName', 'Marca no disponible') }}</div>
                        <h3 class="product-title">{{ p.get('description', 'Sin descripción') }}</h3>
                        <div class="product-sku">
                            SKU:
                            <i class="fas fa-barcode"></i>
                            {{ p.get('ingramPartNumber', 'N/A') }}
                            {% if p.get('vendorPartNumber') %}
                            <br>
                            Vendor Part Number(VPN):
                            <small style="font-size: 0.8em; opacity: 0.8;">
                                <i class="fas fa-tag"></i> {{ p.get('vendorPartNumber') }}
                            </small>
                            {% endif %}
                        </div>
                        <div class="product-details">
                            <div class="product-price">
                                {% if p.get('pricing') and p.get('pricing').get('customerPrice') %}
                                    {% set precio_base = p.get('pricing').get('customerPrice') %}
                                    {% set moneda = p.get('pricing').get('currencyCode', '') %}
                                    {% set precio_final = (precio_base * 1.10) | round(2) %}
                                    {{ moneda }} ${{ precio_final | round(2) }}
                                {% else %}
                                    Consultar precio
                                {% endif %}
                            </div>
                            {% if p.get('availability') %}
                            <div class="product-availability availability-available">
                                <i class="fas fa-check-circle"></i>
                                {{ get_availability_text(p) | truncate(20) }}
                            </div>
                            {% endif %}
                        </div>
                    </div>
                </a>
                {% endfor %}
            </div>

            {% endif %}

            <!-- Paginación profesional -->
            <div class="pagination-container">
                <div class="pagination">
                    {% if page_number > 1 %}
                        <a href="?page={{ page_number - 1 }}&q={{ query }}&vendor={{ vendor }}" class="pagination-btn">
                            <i class="fas fa-chevron-left"></i>
                            Anterior
                        </a>
                    {% else %}
                        <span class="pagination-btn disabled">
                            <i class="fas fa-chevron-left"></i>
                            Anterior
                        </span>
                    {% endif %}

                    <span style="color: #6C757D; font-weight: 500;">
                        Página {{ page_number }} de {{ total_pages }}
                    </span>

                    {% if page_number < total_pages %}
                        <a href="?page={{ page_number + 1 }}&q={{ query }}&vendor={{ vendor }}" class="pagination-btn">
                            Siguiente
                            <i class="fas fa-chevron-right"></i>
                        </a>
                    {% else %}
                        <span class="pagination-btn disabled">
                            Siguiente
                            <i class="fas fa-chevron-right"></i>
                        </span>
                    {% endif %}
                </div>

                <!-- Salto a página específica -->
                <div class="page-jump">
                    <form method="get" style="display: flex; align-items: center; gap: 1rem;">
                        <input type="hidden" name="q" value="{{ query }}">
                        <input type="hidden" name="vendor" value="{{ vendor }}">
                        <label style="color: #1C2A2F; font-weight: 500;">
                            <i class="fas fa-location-arrow"></i>
                            Ir a página:
                        </label>
                        <input type="number" name="page" min="1" max="{{ total_pages }}" 
                               value="{{ page_number }}" class="page-jump input">
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-arrow-right"></i>
                        </button>
                    </form>
                </div>
            </div>
        </div>

        <script>
            // Animaciones y efectos adicionales
            document.addEventListener('DOMContentLoaded', function() {
                // Efecto de hover mejorado en las tarjetas
                const cards = document.querySelectorAll('.product-card');
                cards.forEach(card => {
                    card.addEventListener('mouseenter', function() {
                        this.style.transform = 'translateY(-8px) scale(1.02)';
                    });
                    card.addEventListener('mouseleave', function() {
                        this.style.transform = 'translateY(0) scale(1)';
                    });
                });

                // Auto-focus en el campo de búsqueda
                const searchInput = document.querySelector('input[name="q"]');
                if (searchInput && !searchInput.value) {
                    searchInput.focus();
                }

                // Validación del formulario de salto de página
                const pageInput = document.querySelector('.page-jump input[type="number"]');
                if (pageInput) {
                    pageInput.addEventListener('input', function() {
                        const value = parseInt(this.value);
                        const max = parseInt(this.max);
                        if (value > max) this.value = max;
                        if (value < 1) this.value = 1;
                    });
                }
            });
        </script>
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
        selected_vendor=vendor,
        pagina_vacia=pagina_vacia,
        welcome_message=welcome_message,
        local_vendors=get_local_vendors()
    )

# ---------- DETALLE DE PRODUCTO PROFESIONAL ----------
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

    # En la función producto_detalle, modificar la obtención de la descripción:
    descripcion_larga = (
        detalle.get("extraDescription") or  # Primero extraDescription
        detalle.get("longDescription") or
        detalle.get("productLongDescription") or
        detalle.get("productLongDescr") or
        detalle.get("description") or
        "Este producto ofrece calidad y rendimiento garantizado por Ingram Micro."
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

    # Usar la función mejorada para obtener imagen
    imagen_url = get_image_url_enhanced(detalle)

    # Template HTML profesional para detalle de producto con nueva paleta
    html_template = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{{ detalle.get('description', 'Detalle de Producto') }} | IT Data Global</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                background: #F1F3F4;
                min-height: 100vh;
                color: #1C2A2F;
                line-height: 1.6;
            }

            /* Header profesional */
            .header {
                background: #1C2A2F;
                color: #FFFFFF;
                padding: 1rem 0;
                box-shadow: 0 4px 20px rgba(28, 42, 47, 0.3);
                position: sticky;
                top: 0;
                z-index: 100;
                border-bottom: 3px solid #F15A29;
            }

            .header-content {
                max-width: 1400px;
                margin: 0 auto;
                padding: 0 2rem;
                display: flex;
                align-items: center;
                justify-content: space-between;
            }

            .logo {
                font-size: 2rem;
                font-weight: 700;
                text-decoration: none;
                color: #FFFFFF;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .logo i {
                color: #F15A29;
            }

            .back-btn {
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                padding: 0.8rem 1.5rem;
                background: #F15A29;
                color: #FFFFFF;
                text-decoration: none;
                border-radius: 12px;
                transition: all 0.3s ease;
                font-weight: 500;
            }

            .back-btn:hover {
                background: #d14a1f;
                transform: translateY(-2px);
            }

            /* Container principal */
            .main-container {
                max-width: 1400px;
                margin: 2rem auto;
                padding: 0 2rem;
            }

            /* Breadcrumb */
            .breadcrumb {
                background: #FFFFFF;
                padding: 1rem 1.5rem;
                border-radius: 16px;
                margin-bottom: 2rem;
                box-shadow: 0 4px 20px rgba(28, 42, 47, 0.08);
                border-left: 4px solid #F15A29;
            }

            .breadcrumb-list {
                display: flex;
                align-items: center;
                list-style: none;
                gap: 0.5rem;
                color: #6C757D;
                font-size: 0.9rem;
            }

            .breadcrumb-list a {
                color: #F15A29;
                text-decoration: none;
            }

            .breadcrumb-list a:hover {
                text-decoration: underline;
            }

            /* Layout del producto */
            .product-container {
                background: #FFFFFF;
                border-radius: 24px;
                overflow: hidden;
                box-shadow: 0 20px 60px rgba(28, 42, 47, 0.1);
                border: 1px solid #F1F3F4;
            }

            .product-layout {
                display: grid;
                grid-template-columns: 1fr 1fr;
                min-height: 600px;
            }

            /* Sección de imagen */
            .product-image-section {
                background: #F1F3F4;
                padding: 3rem;
                display: flex;
                align-items: center;
                justify-content: center;
                position: relative;
            }

            .product-image {
                max-width: 100%;
                max-height: 500px;
                object-fit: contain;
                border-radius: 16px;
                box-shadow: 0 10px 40px rgba(28, 42, 47, 0.1);
                transition: transform 0.3s ease;
            }

            .product-image:hover {
                transform: scale(1.05);
            }

            .image-badges {
                position: absolute;
                top: 2rem;
                right: 2rem;
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
            }

            .badge {
                padding: 0.5rem 1rem;
                border-radius: 20px;
                font-size: 0.8rem;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }

            .badge-available {
                background: #F15A29;
                color: #FFFFFF;
            }

            .badge-premium {
                background: #1C2A2F;
                color: #FFFFFF;
            }

            /* Sección de información */
            .product-info-section {
                padding: 3rem;
                display: flex;
                flex-direction: column;
                justify-content: center;
            }

            .product-brand {
                color: #F15A29;
                font-size: 1rem;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 1px;
                margin-bottom: 0.5rem;
            }

            .product-brand i {
                margin-right: 0.5rem;
            }

            .product-title {
                font-size: 2rem;
                font-weight: 700;
                color: #1C2A2F;
                margin-bottom: 1rem;
                line-height: 1.3;
            }

            .product-sku {
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                font-family: 'Monaco', 'Menlo', monospace;
                background: #F1F3F4;
                padding: 0.8rem 1.2rem;
                border-radius: 12px;
                font-size: 0.9rem;
                color: #6C757D;
                margin-bottom: 2rem;
                font-weight: 600;
                width: fit-content;
                border-left: 4px solid #F15A29;
            }

            .product-sku i {
                color: #F15A29;
            }

            .product-price {
                font-size: 2.5rem;
                font-weight: 700;
                color: #F15A29;
                margin-bottom: 1rem;
            }

            .product-availability {
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                padding: 1rem 1.5rem;
                border-radius: 16px;
                font-weight: 600;
                margin-bottom: 2rem;
                font-size: 1rem;
            }

            .availability-available {
                background: #d4edda;
                color: #155724;
                border: 2px solid #c3e6cb;
            }

            .availability-limited {
                background: #fff3cd;
                color: #856404;
                border: 2px solid #ffeaa7;
            }

            /* Secciones de información adicional */
            .product-details {
                margin-top: 2rem;
            }

            .detail-section {
                background: #F1F3F4;
                padding: 2rem;
                border-radius: 16px;
                margin-bottom: 1.5rem;
                border-left: 4px solid #F15A29;
            }

            .detail-section h3 {
                color: #1C2A2F;
                font-size: 1.3rem;
                font-weight: 600;
                margin-bottom: 1rem;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .detail-section h3 i {
                color: #F15A29;
            }

            .detail-section p {
                color: #6C757D;
                line-height: 1.7;
                white-space: pre-line; /* Para mantener los saltos de línea de la descripción */
            }

            .attributes-list {
                list-style: none;
                display: grid;
                gap: 1rem;
            }

            .attribute-item {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 1rem;
                background: #FFFFFF;
                border-radius: 12px;
                box-shadow: 0 2px 8px rgba(28, 42, 47, 0.05);
                border-left: 3px solid #F15A29;
            }

            .attribute-name {
                font-weight: 600;
                color: #1C2A2F;
            }

            .attribute-name i {
                color: #F15A29;
                margin-right: 0.5rem;
            }

            .attribute-value {
                color: #6C757D;
                text-align: right;
            }

            /* Información adicional del producto */
            .product-meta {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 1rem;
                margin-top: 1.5rem;
            }

            .meta-item {
                background: #FFFFFF;
                padding: 1rem;
                border-radius: 12px;
                border-left: 3px solid #F15A29;
            }

            .meta-label {
                font-weight: 600;
                color: #1C2A2F;
                font-size: 0.9rem;
                margin-bottom: 0.5rem;
            }

            .meta-value {
                color: #6C757D;
            }

            /* Botones de acción */
            .action-buttons {
                display: flex;
                gap: 1rem;
                margin-top: 2rem;
            }

            .btn {
                padding: 1rem 2rem;
                border: none;
                border-radius: 12px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s ease;
                text-decoration: none;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 0.5rem;
                font-size: 1rem;
            }

            .btn-primary {
                background: #F15A29;
                color: #FFFFFF;
            }

            .btn-primary:hover {
                background: #d14a1f;
                transform: translateY(-2px);
                box-shadow: 0 8px 25px rgba(241, 90, 41, 0.3);
            }

            .btn-secondary {
                background: #F1F3F4;
                color: #6C757D;
                border: 2px solid #F1F3F4;
            }

            .btn-secondary:hover {
                background: #FFFFFF;
                border-color: #6C757D;
                color: #1C2A2F;
                transform: translateY(-2px);
            }

            /* Responsive Design */
            @media (max-width: 1024px) {
                .product-layout {
                    grid-template-columns: 1fr;
                }

                .product-image-section {
                    padding: 2rem;
                }

                .product-info-section {
                    padding: 2rem;
                }
            }

            @media (max-width: 768px) {
                .main-container {
                    padding: 0 1rem;
                }

                .product-title {
                    font-size: 1.5rem;
                }

                .product-price {
                    font-size: 2rem;
                }

                .action-buttons {
                    flex-direction: column;
                }

                .attribute-item {
                    flex-direction: column;
                    align-items: flex-start;
                    gap: 0.5rem;
                }

                .attribute-value {
                    text-align: left;
                }

                .product-meta {
                    grid-template-columns: 1fr;
                }
            }

            /* Animaciones */
            @keyframes fadeInUp {
                from {
                    opacity: 0;
                    transform: translateY(30px);
                }
                to {
                    opacity: 1;
                    transform: translateY(0);
                }
            }

            .product-container {
                animation: fadeInUp 0.8s ease forwards;
            }

            .detail-section {
                animation: fadeInUp 0.6s ease forwards;
            }

            .detail-section:nth-child(2) { animation-delay: 0.2s; }
            .detail-section:nth-child(3) { animation-delay: 0.4s; }
        </style>
    </head>
    <body>
        <!-- Header Profesional -->
        <header class="header">
            <div class="header-content">
                <a href="/catalogo-completo-cards" class="logo">
                    <i class="fas fa-microchip"></i>
                    IT Data Global
                </a>
                <a href="/catalogo-completo-cards" class="back-btn">
                    <i class="fas fa-arrow-left"></i>
                    Volver al catálogo
                </a>
            </div>
        </header>

        <!-- Container Principal -->
        <div class="main-container">
            <!-- Breadcrumb -->
            <nav class="breadcrumb">
                <ul class="breadcrumb-list">
                    <li><i class="fas fa-home"></i></li>
                    <li><i class="fas fa-chevron-right"></i></li>
                    <li><a href="/catalogo-completo-cards">Catálogo</a></li>
                    <li><i class="fas fa-chevron-right"></i></li>
                    <li>{{ detalle.get('vendorName', 'Producto') }}</li>
                    <li><i class="fas fa-chevron-right"></i></li>
                    <li>{{ part_number }}</li>
                </ul>
            </nav>

            <!-- Container del producto -->
            <div class="product-container">
                <div class="product-layout">
                    <!-- Sección de imagen -->
                    <div class="product-image-section">
                        <img src="{{ imagen_url }}" alt="{{ detalle.get('description', 'Producto') }}" class="product-image">
                        <div class="image-badges">
                            {% if 'Disponible' in disponibilidad %}
                            <div class="badge badge-available">
                                <i class="fas fa-check"></i> En Stock
                            </div>
                            {% endif %}
                            <div class="badge badge-premium">
                                <i class="fas fa-star"></i> Premium
                            </div>
                        </div>
                    </div>

                    <!-- Sección de información -->
                    <div class="product-info-section">
                        <div class="product-brand">
                            <i class="fas fa-tag"></i>
                            {{ detalle.get('vendorName', 'Marca no disponible') }}
                        </div>
                        
                        <h1 class="product-title">{{ detalle.get('description', 'Sin descripción') }}</h1>
                        
                        <div class="product-sku">
                            <i class="fas fa-barcode"></i>
                            <strong>SKU:</strong>
                            {{ detalle.get('ingramPartNumber', part_number) }}
                            
                            {% if detalle.get('vendorPartNumber') %}
                            <br>
                            <small style="font-size: 0.8em; opacity: 0.8; color: #6C757D;">
                                <i class="fas fa-tag"></i>
                                <strong>Vendor Part Number(VPN):</strong> {{ detalle.get('vendorPartNumber') }}
                            </small>
                            {% endif %}
                        </div>

                        <!-- Información adicional del producto -->
                        <div class="product-meta">
                            {% if detalle.get('category') %}
                            <div class="meta-item">
                                <div class="meta-label">
                                    <i class="fas fa-folder"></i> Categoría
                                </div>
                                <div class="meta-value">{{ detalle.get('category') }}</div>
                            </div>
                            {% endif %}

                            {% if detalle.get('subCategory') %}
                            <div class="meta-item">
                                <div class="meta-label">
                                    <i class="fas fa-tags"></i> Subcategoría
                                </div>
                                <div class="meta-value">{{ detalle.get('subCategory') }}</div>
                            </div>
                            {% endif %}

                            {% if detalle.get('upcCode') %}
                            <div class="meta-item">
                                <div class="meta-label">
                                    <i class="fas fa-barcode"></i> UPC Code
                                </div>
                                <div class="meta-value">{{ detalle.get('upcCode') }}</div>
                            </div>
                            {% endif %}
                        </div>

                        <div class="product-price">{{ precio_final }}</div>
                        
                        <div class="product-availability {% if 'Disponible' in disponibilidad %}availability-available{% else %}availability-limited{% endif %}">
                            <i class="fas fa-{% if 'Disponible' in disponibilidad %}check-circle{% else %}exclamation-circle{% endif %}"></i>
                            {{ disponibilidad }}
                        </div>

                        <div class="action-buttons">
                            <button class="btn btn-primary" onclick="alert('Funcionalidad de cotización próximamente')">
                                <i class="fas fa-shopping-cart"></i>
                                Solicitar cotización
                            </button>
                            <button class="btn btn-secondary" onclick="alert('Funcionalidad de favoritos próximamente')">
                                <i class="fas fa-heart"></i>
                                Agregar a favoritos
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Detalles adicionales -->
            <div class="product-details">
                <!-- Descripción -->
                <div class="detail-section">
                    <h3>
                        <i class="fas fa-info-circle"></i>
                        Descripción del producto
                    </h3>
                    <p>{{ descripcion_larga }}</p>
                </div>

                <!-- Especificaciones técnicas -->
                {% if atributos %}
                <div class="detail-section">
                    <h3>
                        <i class="fas fa-cogs"></i>
                        Especificaciones técnicas
                    </h3>
                    <ul class="attributes-list">
                        {% for a in atributos %}
                        <li class="attribute-item">
                            <span class="attribute-name">{{ a.name }}</span>
                            <span class="attribute-value">{{ a.value }}</span>
                        </li>
                        {% endfor %}
                    </ul>
                </div>
                {% endif %}

                <!-- Información adicional -->
                <div class="detail-section">
                    <h3>
                        <i class="fas fa-shield-alt"></i>
                        Información adicional
                    </h3>
                    <div style="display: grid; gap: 1rem;">
                        <div class="attribute-item">
                            <span class="attribute-name">
                                <i class="fas fa-truck"></i>
                                Envío
                            </span>
                            <span class="attribute-value">Disponible a toda la república</span>
                        </div>
                        {% if detalle.get('endUserRequired') %}
                        <div class="attribute-item">
                            <span class="attribute-name">
                                <i class="fas fa-user"></i>
                                Requiere usuario final
                            </span>
                            <span class="attribute-value">{{ 'Sí' if detalle.get('endUserRequired') == 'True' else 'No' }}</span>
                        </div>
                        {% endif %}
                        {% if detalle.get('hasWarranty') %}
                        <div class="attribute-item">
                            <span class="attribute-name">
                                <i class="fas fa-certificate"></i>
                                Garantía
                            </span>
                            <span class="attribute-value">{{ 'Sí' if detalle.get('hasWarranty') == 'True' else 'No' }}</span>
                        </div>
                        {% endif %}
                    </div>
                </div>
            </div>
        </div>

        <script>
            // Efectos y funcionalidades adicionales
            document.addEventListener('DOMContentLoaded', function() {
                // Efecto de zoom en la imagen
                const productImage = document.querySelector('.product-image');
                if (productImage) {
                    productImage.addEventListener('click', function() {
                        if (this.style.transform === 'scale(2)') {
                            this.style.transform = 'scale(1)';
                            this.style.cursor = 'zoom-in';
                        } else {
                            this.style.transform = 'scale(2)';
                            this.style.cursor = 'zoom-out';
                        }
                    });
                }

                // Animaciones de aparición progresiva
                const sections = document.querySelectorAll('.detail-section');
                const observer = new IntersectionObserver((entries) => {
                    entries.forEach(entry => {
                        if (entry.isIntersecting) {
                            entry.target.style.opacity = '1';
                            entry.target.style.transform = 'translateY(0)';
                        }
                    });
                });

                sections.forEach(section => {
                    section.style.opacity = '0';
                    section.style.transform = 'translateY(30px)';
                    section.style.transition = 'all 0.6s ease';
                    observer.observe(section);
                });

                // Copiar SKU al clipboard
                const skuElement = document.querySelector('.product-sku');
                if (skuElement) {
                    skuElement.addEventListener('click', function() {
                        const sku = this.textContent.trim().replace('📊', '').trim();
                        navigator.clipboard.writeText(sku).then(() => {
                            // Mostrar feedback visual
                            const originalBackground = this.style.background;
                            this.innerHTML = '<i class="fas fa-check" style="color: #F15A29;"></i> SKU copiado';
                            this.style.background = '#d4edda';
                            this.style.color = '#155724';
                            this.style.borderColor = '#c3e6cb';
                            
                            setTimeout(() => {
                                this.innerHTML = originalBackground;
                                this.style.background = '#F1F3F4';
                                this.style.color = '#6C757D';
                                this.style.borderColor = '#F15A29';
                            }, 2000);
                        });
                    });
                    
                    // Añadir cursor pointer
                    skuElement.style.cursor = 'pointer';
                    skuElement.title = 'Clic para copiar SKU';
                }
            });
        </script>
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)