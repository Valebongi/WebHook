# Análisis de Arquitectura y Propuesta para Segundo Formulario de WordPress

## 📋 Estado Actual - Endpoint `/leads`

### Flujo Actual
1. **Entrada**: Payload JSON del formulario WP con:
   - `nombre_capacitacion` (el nombre del producto/curso)
   - `nombres_apellidos`
   - `telefono`
   - `correo`
   - `form_id`, `entry_id`, `fecha_formulario` (opcionales)

2. **Procesamiento**:
   - ✅ Validación Pydantic + parseo de teléfono
   - ✅ Lookup del país desde prefijo telefónico
   - ✅ **Lookup del Producto por nombre** (3 estrategias: exacto → prefijo → substring)
   - ✅ Dedupe por email + CodigoLanzamiento
   - ✅ Creación transaccional: Persona → PotencialCliente → Oportunidad → HistorialEstado → Inversion
   - ⚠️ Si no hay match de producto → Lead en pendientes (`Wordpress_Lead_Pendiente`)

3. **Respuestas HTTP**:
   - `201 Created`: Oportunidad creada exitosamente
   - `202 Accepted`: Lead guardado en pendientes (sin producto match)
   - `409 Conflict`: Duplicado (mismo email + producto activo)

### Base de Datos - Tablas Clave
```
adm.Persona              (IdPais, Nombres, Apellidos, Celular, PrefijoPaisCelular, Correo, ...)
adm.PotencialCliente     (IdPersona, ...)
adm.Oportunidad          (IdPotencialCliente, IdProducto, CodigoLanzamiento, Origen, ...)
adm.Producto             (Id, Nombre, CodigoLanzamiento, CodigoLinkedin, CostoBase, EstadoProductoTipoId, ...)
adm.HistorialEstado      (IdOportunidad, IdEstado, IdPersonal, ...)
adm.Inversion            (IdOportunidad, IdProducto, CostoTotal, ...)
adm.OportunidadAutoAsignacionLog (si hay auto-asignación)
adm.Wordpress_Lead_Pendiente (leads sin match)
```

---

## 🆕 Nuevo Endpoint - Propuesta para Segundo Formulario

### Requisito del Negocio
- Nuevo formulario WordPress **NO trae código de producto**
- Los datos no pueden matchear contra el catálogo de productos
- Necesitamos asignarles un **código de producto genérico** en BD
- Deben poder crear oportunidades normalmente
- Usar el mismo flujo de auto-asignación de asesor

### Solución Propuesta

#### 1. **Crear Producto Genérico en BD**
En **OlympusDB_QA** (y luego en PROD), crear un producto "comodín":
```sql
-- Ejemplo: ejecutar una única vez en QA
INSERT INTO adm.Producto 
  (Nombre, CodigoLanzamiento, CodigoLinkedin, CostoBase, 
   EstadoProductoTipoId, Estado, FechaCreacion, UsuarioCreacion, ...)
VALUES 
  ('GENERICO - Formulario WP 2', 'PROD-GENERICO-WP2', 'GENERICO-WP2', 0,
   20, 1, GETDATE(), 'SYSTEM-WP', ...)
```
- Nos daremos el **Id** de este producto (ej: Id=999)
- Este Id se usa para TODOS los leads de este formulario

#### 2. **Nuevo Modelo Pydantic**
Crear `models/wordpress_lead_generic.py`:
```python
class WordpressLeadGenericPayload(BaseModel):
    """Para formularios que NO traen nombre de producto."""
    nombres_apellidos: str          # Similar al actual
    telefono: str
    correo: EmailStr
    # Posibles campos adicionales específicos del nuevo form:
    descripcion_consulta: Optional[str]  # Ej: "Consulta sobre...", "Interesado en..."
    referencia_externa: Optional[str]     # ID o ref de WP del formulario
    form_id: Optional[int]
    entry_id: Optional[int]
    fecha_formulario: Optional[datetime]
```

#### 3. **Nuevo Endpoint**
```http
POST /leads-generic
X-API-Key: [misma clave de auth]

{
  "nombres_apellidos": "Juan Pérez García",
  "telefono": "+57 310 456 7890",
  "correo": "juan@example.com",
  "descripcion_consulta": "Interesado en capacitación",
  "form_id": 42,
  "entry_id": 123
}
```

#### 4. **Servicio de Procesamiento**
Crear `services/lead_generic_service.py`:
```python
def process_wordpress_lead_generic(
    payload: WordpressLeadGenericPayload,
    generic_producto_id: int = GENERIC_PRODUCTO_ID  # Ej: 999
) -> dict:
    """
    Procesa un lead sin match de producto.
    Diferencias vs. process_wordpress_lead:
    - NO hace lookup de producto por nombre
    - USA EL PRODUCTO GENÉRICO DIRECTO
    - Resto del pipeline idéntico (país, dedupe, creación de opp)
    """
```

#### 5. **Configuración**
Agregar a `config.py`:
```python
# Producto genérico para el formulario sin código de producto
GENERIC_PRODUCTO_ID = int(os.getenv("GENERIC_PRODUCTO_ID", "999"))
GENERIC_CODIGO_LANZAMIENTO = os.getenv(
    "GENERIC_CODIGO_LANZAMIENTO", 
    "PROD-GENERICO-WP2"
)
```

#### 6. **Actualizar `api.py`**
```python
from models.wordpress_lead_generic import WordpressLeadGenericPayload
from services.lead_generic_service import process_wordpress_lead_generic

@app.post(
    "/leads-generic",
    dependencies=[Depends(require_api_key)],
    summary="Recibe un lead desde formulario WP sin código de producto."
)
async def create_lead_generic(request: Request):
    # Similar a create_lead pero llama a process_wordpress_lead_generic
    # ...
```

---

## 🔍 Diferencias Clave

| Aspecto | `/leads` (Actual) | `/leads-generic` (Nuevo) |
|--------|-------------------|-------------------------|
| **Input requerido** | `nombre_capacitacion` | Cualquier descripción/referencia |
| **Lookup de Producto** | ✅ Búsqueda 3-pasos por nombre | ❌ Usamos Id fijo |
| **Dedicación a Producto** | Variable (1 de N) | Fijo (siempre el mismo) |
| **Si no hay match** | Lead en pendientes | Crea opp igual (con genérico) |
| **Dedupe** | Por email + CodigoLanzamiento | Por email + CodigoLanzamiento |
| **Auto-asignación asesor** | ✅ Sí | ✅ Sí (igual) |
| **Respuestas** | 201/202/409 | 201/409 (nunca pendiente) |

---

## 📊 Ventajas de la Solución

✅ **Reutilización maximal**: ~90% del código existente se reutiliza  
✅ **Consistencia**: Mismo pipeline de creación de oportunidades  
✅ **Escalable**: Fácil agregar más formularios con otros productos genéricos  
✅ **Trazabilidad**: Se registra en `Oportunidad.Origen` y logs  
✅ **QA friendly**: Producto genérico solo en QA hasta validar  
✅ **Reversible**: Si el producto genérico no existe, falla claro (FK constraint)  

---

## 🚀 Pasos de Implementación (en orden)

### Fase 1: BD (QA)
1. Crear producto genérico en OlympusDB_QA
2. Verificar que el producto tenga `EstadoProductoTipoId IN (17, 19, 20)`
3. Anotar el Id y CodigoLanzamiento

### Fase 2: Código
1. Crear `models/wordpress_lead_generic.py`
2. Crear `services/lead_generic_service.py` (basado en lead_service.py)
3. Actualizar `config.py` (añadir GENERIC_PRODUCTO_ID, etc.)
4. Agregar endpoint `/leads-generic` a `api.py`
5. Actualizar `.env.example`

### Fase 3: Testing
1. Tests unitarios para parseo del nuevo modelo
2. Tests de integración: lead → BD
3. Validar auto-asignación funciona
4. Validar dedupe funciona
5. Dashboard actualizado para ver ambos endpoints

### Fase 4: Validación en QA
1. Probar con datos reales del segundo formulario
2. Revisar `adm.Wordpress_Lead_Pendiente` (debería estar vacío)
3. Verificar oportunidades en `adm.Oportunidad`

---

## 💡 Consideraciones Adicionales

- **¿Qué hacer si el producto genérico se marca como inactivo?**  
  → Fail-fast: FK constraint genera error 500 claro.

- **¿Si necesitamos múltiples productos "comodín"?**  
  → Crear un campo en el payload o env var por tipo de formulario.

- **¿Historial de cuál formulario generó cada opp?**  
  → Se puede guardar en `HistorialEstado.Observaciones` o crear FK a tabla de formularios.

- **¿Métricas diferenciadas?**  
  → El dashboard ya muestra `request_log` con `result` y logs; fácil filtrar por endpoint.

