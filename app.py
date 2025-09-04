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

# Token global
TOKEN = None
TOKEN_EXPIRY = 0


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


def get_image_url_from(item):
    """Extrae la URL de imagen de estructuras comunes (productImages) o devuelve placeholder."""
    try:
        imgs = item.get("productImages") or item.get("productImageList") or []
        if imgs and isinstance(imgs, list):
            first = imgs[0]
            # posibles keys: 'url', 'imageUrl', 'imageURL'
            return first.get("url") or first.get("imageUrl") or first.get("imageURL")
    except Exception:
        pass
    return "https://via.placeholder.com/250"
    
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
    <!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Catálogo de Productos | It Data Global</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {
            background: #f8f9fa;
            padding: 20px;
        }
        .card {
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 10px rgba(0,0,0,0.1);
            height: 100%;
            transition: transform 0.3s ease;
        }
        .card:hover {
            transform: translateY(-5px);
        }
        .card-img-top {
            height: 200px;
            object-fit: contain;
            padding: 15px;
            background: #f8f9fa;
        }
        .product-sku {
            font-size: 0.85rem;
            margin-bottom: 10px;
        }
        .sku-item {
            padding: 0.3rem 0;
            border-bottom: 1px dashed #dee2e6;
        }
        .sku-item:last-child {
            border-bottom: none;
        }
        .badge-custom {
            display: inline-block;
            background: #f1f3f5;
            padding: 0.3rem 0.6rem;
            border-radius: 6px;
            margin-bottom: 0.3rem;
            font-size: 0.75rem;
        }
        .availability {
            font-size: 0.9rem;
            margin: 10px 0;
        }
        .pagination {
            margin-top: 20px;
        }
        .search-form {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1 class="my-4 text-center">Catálogo de Productos</h1>
        
        <!-- Formulario de búsqueda -->
        <div class="search-form">
            <form method="GET" class="row g-3">
                <div class="col-md-5">
                    <input type="text" class="form-control" name="q" value="{{ query }}" placeholder="Buscar productos...">
                </div>
                <div class="col-md-3">
                    <input type="text" class="form-control" name="vendor" value="{{ vendor }}" placeholder="Filtrar por marca...">
                </div>
                <div class="col-md-2">
                    <select class="form-select" name="page_size">
                        <option value="25" {% if request.args.get('page_size', '25') == '25' %}selected{% endif %}>25 por página</option>
                        <option value="50" {% if request.args.get('page_size') == '50' %}selected{% endif %}>50 por página</option>
                    </select>
                </div>
                <div class="col-md-2">
                    <button type="submit" class="btn btn-primary w-100">Buscar</button>
                </div>
            </form>
        </div>

        <!-- Información de resultados -->
        {% if total_records > 0 %}
        <div class="alert alert-info">
            Mostrando {{ start_record }} - {{ end_record }} de {{ total_records }} productos
            {% if query %}para "{{ query }}"{% endif %}
            {% if vendor %}de la marca "{{ vendor }}"{% endif %}
        </div>
        {% endif %}

        <!-- Grid de productos -->
        <div class="row row-cols-1 row-cols-md-2 row-cols-lg-3 row-cols-xl-4 g-4">
            {% for p in productos %}
            <div class="col">
                <div class="card h-100">
                    <img src="{{ get_image_url_enhanced(p) }}" class="card-img-top" alt="{{ p.get('description', 'Producto') }}">
                    <div class="card-body">
                        <h6 class="card-title">{{ p.get('vendorName', 'Marca no disponible') }}</h6>
                        <p class="card-text">{{ p.get('description', 'Descripción no disponible')|truncate(80) }}</p>
                        
                        <!-- SKU y Vendor Part Number - CORREGIDO -->
                        <div class="product-sku">
                            <div class="sku-item">
                                <small class="text-muted">
                                    <i class="fas fa-barcode"></i> 
                                    <strong>SKU:</strong> {{ p.get('ingramPartNumber', 'N/A') }}
                                </small>
                            </div>
                            {% if p.get('vendorPartNumber') %}
                            <div class="sku-item">
                                <small class="text-muted">
                                    <i class="fas fa-tag"></i> 
                                    <strong>Vendor PN:</strong> {{ p.get('vendorPartNumber') }}
                                </small>
                            </div>
                            {% endif %}
                        </div>
                        
                        <!-- Precio -->
                        {% if p.pricing and p.pricing.customerPrice %}
                        <div class="h5 text-success mt-2">
                            ${{ "%.2f"|format(p.pricing.customerPrice * 1.1) }} MXN
                        </div>
                        {% endif %}
                        
                        <!-- Disponibilidad -->
                        <div class="availability">
                            <small>{{ get_availability_text(p) }}</small>
                        </div>
                        
                        <!-- Botones de acción -->
                        <div class="d-grid gap-2">
                            <a href="/producto/{{ p.get('ingramPartNumber') }}" class="btn btn-outline-primary btn-sm">
                                <i class="fas fa-eye"></i> Ver detalles
                            </a>
                        </div>
                    </div>
                </div>
            </div>
            {% else %}
            <div class="col-12">
                <div class="alert alert-warning text-center">
                    {% if query or vendor %}
                    No se encontraron productos con los criterios de búsqueda.
                    {% else %}
                    No hay productos disponibles en este momento.
                    {% endif %}
                </div>
            </div>
            {% endfor %}
        </div>

        <!-- Paginación -->
        {% if total_pages > 1 %}
        <nav aria-label="Page navigation">
            <ul class="pagination justify-content-center">
                <li class="page-item {% if page_number == 1 %}disabled{% endif %}">
                    <a class="page-link" href="{{ url_for('catalogo_completo_cards', page=page_number-1, q=query, vendor=vendor) }}">Anterior</a>
                </li>
                
                {% for p in range(1, total_pages+1) %}
                    {% if p >= page_number-2 and p <= page_number+2 %}
                    <li class="page-item {% if p == page_number %}active{% endif %}">
                        <a class="page-link" href="{{ url_for('catalogo_completo_cards', page=p, q=query, vendor=vendor) }}">{{ p }}</a>
                    </li>
                    {% endif %}
                {% endfor %}
                
                <li class="page-item {% if page_number == total_pages %}disabled{% endif %}">
                    <a class="page-link" href="{{ url_for('catalogo_completo_cards', page=page_number+1, q=query, vendor=vendor) }}">Siguiente</a>
                </li>
            </ul>
        </nav>
        {% endif %}
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
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

    # Usar la función mejorada para obtener imagen
    imagen_url = get_image_url_enhanced(detalle)

    # Template HTML profesional para detalle de producto
    html_template = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{{ detalle.get('description', 'Detalle de Producto') }} | It Data Global</title>
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
                background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
                min-height: 100vh;
                color: #2d3748;
                line-height: 1.6;
            }

            /* Header profesional */
            .header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 1rem 0;
                box-shadow: 0 4px 20px rgba(0,0,0,0.1);
                position: sticky;
                top: 0;
                z-index: 100;
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
                color: white;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .back-btn {
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                padding: 0.8rem 1.5rem;
                background: rgba(255,255,255,0.2);
                color: white;
                text-decoration: none;
                border-radius: 12px;
                transition: all 0.3s ease;
                font-weight: 500;
                backdrop-filter: blur(10px);
            }

            .back-btn:hover {
                background: rgba(255,255,255,0.3);
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
                background: rgba(255,255,255,0.9);
                padding: 1rem 1.5rem;
                border-radius: 16px;
                margin-bottom: 2rem;
                backdrop-filter: blur(10px);
                box-shadow: 0 4px 20px rgba(0,0,0,0.08);
            }

            .breadcrumb-list {
                display: flex;
                align-items: center;
                list-style: none;
                gap: 0.5rem;
                color: #718096;
                font-size: 0.9rem;
            }

            .breadcrumb-list a {
                color: #667eea;
                text-decoration: none;
            }

            .breadcrumb-list a:hover {
                text-decoration: underline;
            }

            /* Layout del producto */
            .product-container {
                background: white;
                border-radius: 24px;
                overflow: hidden;
                box-shadow: 0 20px 60px rgba(0,0,0,0.1);
                backdrop-filter: blur(10px);
            }

            .product-layout {
                display: grid;
                grid-template-columns: 1fr 1fr;
                min-height: 600px;
            }

            /* Sección de imagen */
            .product-image-section {
                background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
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
                box-shadow: 0 10px 40px rgba(0,0,0,0.1);
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
                background: linear-gradient(135deg, #48bb78 0%, #38a169 100%);
                color: white;
            }

            .badge-premium {
                background: linear-gradient(135deg, #ed8936 0%, #dd6b20 100%);
                color: white;
            }

            /* Sección de información */
            .product-info-section {
                padding: 3rem;
                display: flex;
                flex-direction: column;
                justify-content: center;
            }

            .product-brand {
                color: #667eea;
                font-size: 1rem;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 1px;
                margin-bottom: 0.5rem;
            }

            .product-title {
                font-size: 2rem;
                font-weight: 700;
                color: #2d3748;
                margin-bottom: 1rem;
                line-height: 1.3;
            }

            .product-sku {
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                font-family: 'Monaco', 'Menlo', monospace;
                background: linear-gradient(135deg, #edf2f7 0%, #e2e8f0 100%);
                padding: 0.8rem 1.2rem;
                border-radius: 12px;
                font-size: 0.9rem;
                color: #4a5568;
                margin-bottom: 2rem;
                font-weight: 600;
                width: fit-content;
            }

            .product-price {
                font-size: 2.5rem;
                font-weight: 700;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
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
                background: linear-gradient(135deg, #c6f6d5 0%, #9ae6b4 100%);
                color: #22543d;
            }

            .availability-limited {
                background: linear-gradient(135deg, #feebc8 0%, #f6d55c 100%);
                color: #9c4221;
            }

            /* Secciones de información adicional */
            .product-details {
                margin-top: 2rem;
            }

            .detail-section {
                background: #f7fafc;
                padding: 2rem;
                border-radius: 16px;
                margin-bottom: 1.5rem;
            }

            .detail-section h3 {
                color: #2d3748;
                font-size: 1.3rem;
                font-weight: 600;
                margin-bottom: 1rem;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .detail-section p {
                color: #4a5568;
                line-height: 1.7;
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
                background: white;
                border-radius: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.05);
            }

            .attribute-name {
                font-weight: 600;
                color: #2d3748;
            }

            .attribute-value {
                color: #718096;
                text-align: right;
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
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }

            .btn-primary:hover {
                transform: translateY(-2px);
                box-shadow: 0 8px 25px rgba(102, 126, 234, 0.3);
            }

            .btn-secondary {
                background: #f7fafc;
                color: #4a5568;
                border: 2px solid #e2e8f0;
            }

            .btn-secondary:hover {
                background: #edf2f7;
                border-color: #cbd5e0;
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
                    It Data Global
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
                            {{ detalle.get('ingramPartNumber') or part_number }}
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
                            <span class="attribute-value">Disponible en toda la república</span>
                        </div>
                        <div class="attribute-item">
                            <span class="attribute-name">
                                <i class="fas fa-medal"></i>
                                Garantía
                            </span>
                            <span class="attribute-value">Garantía oficial del fabricante</span>
                        </div>
                        <div class="attribute-item">
                            <span class="attribute-name">
                                <i class="fas fa-headset"></i>
                                Soporte técnico
                            </span>
                            <span class="attribute-value">Soporte especializado disponible</span>
                        </div>
                        <div class="attribute-item">
                            <span class="attribute-name">
                                <i class="fas fa-certificate"></i>
                                Distribuidor oficial
                            </span>
                            <span class="attribute-value">Ingram Micro - Distribuidor autorizado</span>
                        </div>
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
                            const originalText = this.innerHTML;
                            this.innerHTML = '<i class="fas fa-check"></i> SKU copiado';
                            this.style.background = 'linear-gradient(135deg, #c6f6d5 0%, #9ae6b4 100%)';
                            
                            setTimeout(() => {
                                this.innerHTML = originalText;
                                this.style.background = 'linear-gradient(135deg, #edf2f7 0%, #e2e8f0 100%)';
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