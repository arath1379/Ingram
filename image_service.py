import os
import requests
import time
from urllib.parse import quote

class ProductImageService:
    """
    Servicio para buscar imágenes de productos usando múltiples APIs
    con sistema de fallback y caché.
    """
    
    def __init__(self):
        self.google_api_key = os.getenv("GOOGLE_API_KEY")
        self.google_search_engine_id = os.getenv("GOOGLE_SEARCH_ENGINE_ID")
        self.serpapi_key = os.getenv("SERPAPI_KEY")
        self.bing_api_key = os.getenv("BING_IMAGE_API_KEY")
        
        # Cache simple en memoria (en producción usar Redis)
        self.image_cache = {}
        
    def get_product_image(self, producto_nombre, marca="", sku=""):
        """
        Busca imagen para un producto con sistema de fallback.
        
        Args:
            producto_nombre (str): Nombre/descripción del producto
            marca (str): Marca del producto
            sku (str): SKU o número de parte
            
        Returns:
            str: URL de la primera imagen encontrada o placeholder
        """
        
        # Crear clave de caché
        cache_key = f"{marca}_{producto_nombre}_{sku}".lower().replace(" ", "_")
        
        # Verificar caché
        if cache_key in self.image_cache:
            return self.image_cache[cache_key]
        
        # Limpiar y preparar términos de búsqueda
        search_terms = self._prepare_search_terms(producto_nombre, marca, sku)
        
        # Intentar APIs en orden de prioridad
        image_url = None
        
        # 1. Intentar Google Custom Search
        if self.google_api_key and self.google_search_engine_id:
            image_url = self._search_google_images(search_terms)
            if image_url:
                self.image_cache[cache_key] = image_url
                return image_url
        
        # 2. Intentar SerpApi
        if self.serpapi_key:
            image_url = self._search_serpapi_images(search_terms)
            if image_url:
                self.image_cache[cache_key] = image_url
                return image_url
        
        # 3. Intentar Bing Images
        if self.bing_api_key:
            image_url = self._search_bing_images(search_terms)
            if image_url:
                self.image_cache[cache_key] = image_url
                return image_url
        
        # 4. Fallback: placeholder
        placeholder = "https://via.placeholder.com/300x300/f8f9fa/6c757d?text=Sin+Imagen"
        self.image_cache[cache_key] = placeholder
        return placeholder
    
    def _prepare_search_terms(self, producto_nombre, marca, sku):
        """Prepara términos de búsqueda optimizados."""
        
        # Limpiar descripción del producto
        producto_limpio = producto_nombre.replace(",", "").replace("-", " ")
        
        # Crear variantes de búsqueda
        terms = []
        
        if marca and sku:
            terms.append(f"{marca} {sku}")
            terms.append(f"{marca} {producto_limpio}")
        elif marca:
            terms.append(f"{marca} {producto_limpio}")
        elif sku:
            terms.append(f"{sku} product image")
        else:
            terms.append(producto_limpio)
        
        return terms
    
    def _search_google_images(self, search_terms):
        """Buscar usando Google Custom Search API."""
        
        for term in search_terms:
            try:
                params = {
                    'key': self.google_api_key,
                    'cx': self.google_search_engine_id,
                    'q': term,
                    'searchType': 'image',
                    'num': 3,
                    'imgSize': 'medium',
                    'imgType': 'photo',
                    'safe': 'active',
                    'fileType': 'jpg,png'
                }
                
                response = requests.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params=params,
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    items = data.get('items', [])
                    
                    for item in items:
                        image_url = item.get('link')
                        if image_url and self._validate_image_url(image_url):
                            return image_url
                            
                # Rate limiting
                time.sleep(0.1)
                
            except Exception as e:
                print(f"Error en Google Images: {e}")
                continue
        
        return None
    
    def _search_serpapi_images(self, search_terms):
        """Buscar usando SerpApi."""
        
        for term in search_terms:
            try:
                params = {
                    "engine": "google_images",
                    "q": term,
                    "api_key": self.serpapi_key,
                    "num": 5,
                    "ijn": "0"
                }
                
                response = requests.get(
                    "https://serpapi.com/search",
                    params=params,
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    images = data.get("images_results", [])
                    
                    for img in images:
                        image_url = img.get("original")
                        if image_url and self._validate_image_url(image_url):
                            return image_url
                
                time.sleep(0.2)
                
            except Exception as e:
                print(f"Error en SerpApi: {e}")
                continue
        
        return None
    
    def _search_bing_images(self, search_terms):
        """Buscar usando Bing Image Search API."""
        
        for term in search_terms:
            try:
                headers = {
                    'Ocp-Apim-Subscription-Key': self.bing_api_key,
                }
                
                params = {
                    'q': term,
                    'count': 5,
                    'offset': 0,
                    'mkt': 'en-us',
                    'imageType': 'Photo'
                }
                
                response = requests.get(
                    "https://api.bing.microsoft.com/v7.0/images/search",
                    headers=headers,
                    params=params,
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    images = data.get("value", [])
                    
                    for img in images:
                        image_url = img.get("contentUrl")
                        if image_url and self._validate_image_url(image_url):
                            return image_url
                
                time.sleep(0.1)
                
            except Exception as e:
                print(f"Error en Bing Images: {e}")
                continue
        
        return None
    
    def _validate_image_url(self, url):
        """Valida que la URL sea una imagen válida y accesible."""
        
        if not url or not url.startswith(('http://', 'https://')):
            return False
        
        # Filtrar URLs problemáticas
        blocked_domains = ['facebook.com', 'instagram.com', 'pinterest.com']
        if any(domain in url.lower() for domain in blocked_domains):
            return False
        
        # Verificar extensiones de imagen
        valid_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp')
        if not any(ext in url.lower() for ext in valid_extensions):
            return False
        
        try:
            # Verificar que la URL sea accesible (solo HEAD request)
            response = requests.head(url, timeout=5, allow_redirects=True)
            content_type = response.headers.get('content-type', '').lower()
            return (response.status_code == 200 and 
                    content_type.startswith('image/'))
        except:
            return False
    
    def get_multiple_images(self, producto_nombre, marca="", sku="", max_images=3):
        """
        Obtiene múltiples imágenes para un producto.
        
        Returns:
            list: Lista de URLs de imágenes
        """
        
        search_terms = self._prepare_search_terms(producto_nombre, marca, sku)
        images = []
        
        # Usar la primera API disponible para obtener múltiples imágenes
        if self.google_api_key and self.google_search_engine_id:
            images = self._get_multiple_google_images(search_terms[0], max_images)
        elif self.serpapi_key:
            images = self._get_multiple_serpapi_images(search_terms[0], max_images)
        
        return images if images else [self.get_product_image(producto_nombre, marca, sku)]
    
    def _get_multiple_google_images(self, search_term, max_images):
        """Obtiene múltiples imágenes de Google."""
        
        try:
            params = {
                'key': self.google_api_key,
                'cx': self.google_search_engine_id,
                'q': search_term,
                'searchType': 'image',
                'num': max_images,
                'imgSize': 'medium',
                'imgType': 'photo',
                'safe': 'active'
            }
            
            response = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params=params,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                items = data.get('items', [])
                
                valid_images = []
                for item in items:
                    image_url = item.get('link')
                    if image_url and self._validate_image_url(image_url):
                        valid_images.append(image_url)
                
                return valid_images
        
        except Exception as e:
            print(f"Error obteniendo múltiples imágenes: {e}")
        
        return []


# Instancia global del servicio
image_service = ProductImageService()


def get_image_url_from_enhanced(item):
    """
    Versión mejorada que usa el servicio de búsqueda de imágenes.
    Primero intenta obtener de Ingram, luego busca en APIs externas.
    """
    
    # 1. Intentar obtener imagen de Ingram primero
    try:
        imgs = item.get("productImages") or item.get("productImageList") or []
        if imgs and isinstance(imgs, list):
            first = imgs[0]
            ingram_url = first.get("url") or first.get("imageUrl") or first.get("imageURL")
            if ingram_url and ingram_url != "https://via.placeholder.com/250":
                return ingram_url
    except Exception:
        pass
    
    # 2. Si no hay imagen de Ingram, buscar externamente
    producto_nombre = item.get("description", "")
    marca = item.get("vendorName", "")
    sku = item.get("ingramPartNumber", "")
    
    if producto_nombre or sku:
        return image_service.get_product_image(producto_nombre, marca, sku)
    
    # 3. Fallback final
    return "https://via.placeholder.com/300x300/f8f9fa/6c757d?text=Sin+Imagen"