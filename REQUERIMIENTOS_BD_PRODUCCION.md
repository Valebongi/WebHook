# Requerimientos de BD para habilitar WebHook en Produccion

## 1. Objetivo
Definir los cambios minimos en Base de Datos para que el flujo de formularios WordPress funcione correctamente en produccion, incluyendo el nuevo endpoint `POST /leads-generic`.

## 2. Contexto funcional
El backend ya esta desplegado y operativo. Para que el procesamiento de leads funcione en produccion, la BD debe tener:

- Estructura para leads pendientes.
- Producto generico para formularios sin producto estandarizado.
- Permisos suficientes para el usuario tecnico de la API.

## 3. Cambios obligatorios en BD

### 3.1 Tabla de pendientes (si no existe)
Archivo de referencia:
- `sql/001_Wordpress_Lead_Pendiente.sql`

Requerido para:
- Endpoint `POST /leads` cuando no hay match de producto.
- Casos de telefono no parseable.

Estado esperado:
- Tabla `adm.Wordpress_Lead_Pendiente` creada.
- Indices de soporte creados (`IX_WpLeadPendiente_Estado`, `IX_WpLeadPendiente_Email`).

### 3.2 Producto generico para formulario sin producto
Archivo de referencia:
- `sql/002_Producto_Generico_WP2.sql`

Requerido para:
- Endpoint `POST /leads-generic`.

Estado esperado:
- Existe un registro activo en `adm.Producto` con:
  - `CodigoLanzamiento = 'PROD-GENERICO-WP2'`
  - `Nombre = 'GENERICO - Formulario WP 2'`
  - `Estado = 1`
  - `EstadoProductoTipoId = 20` (o equivalente permitido por negocio)

Resultado QA ya verificado:
- En QA se creo correctamente con `Id = 310`.

Nota para produccion:
- El Id en produccion puede ser distinto (normalmente lo sera).
- Lo importante es mantener `CodigoLanzamiento` unico y activo.

## 4. Variables de entorno relacionadas (backend)
Aunque no son objetos de BD, estas variables deben apuntar a la BD de produccion para que el cambio sea efectivo:

Obligatorias:
- `DB_SERVER`
- `DB_NAME` (produccion)
- `DB_USER`
- `DB_PASSWORD`
- `DB_DRIVER`
- `WORDPRESS_API_KEY`

Para flujo generico:
- `GENERIC_PRODUCTO_ID` (recomendado: Id real en prod)
- `GENERIC_PRODUCTO_CODIGO_LANZAMIENTO` (recomendado: `PROD-GENERICO-WP2`)
- `GENERIC_PRODUCTO_NOMBRE` (recomendado: `GENERICO - Formulario WP 2`)

Opcional segun estrategia de catalogo:
- `PRODUCTS_DB_NAME`

## 5. Permisos requeridos para el usuario de la API
Usuario tecnico configurado en `DB_USER` debe tener permisos sobre esquema `adm` y `mdm` para estas operaciones:

Select:
- `adm.Producto`
- `adm.Persona`
- `adm.PotencialCliente`
- `adm.Oportunidad`
- `adm.HistorialEstado`
- `adm.Personal`
- `mdm.Pais`

Insert:
- `adm.Persona`
- `adm.PotencialCliente`
- `adm.Oportunidad`
- `adm.HistorialEstado`
- `adm.Inversion`
- `adm.OportunidadAutoAsignacionLog`
- `adm.Wordpress_Lead_Pendiente`

Update (si aplica a procesos operativos futuros):
- No obligatorio para el flujo minimo actual.

## 6. Script de implementacion sugerido (orden)
Ejecutar en produccion:

1. `sql/001_Wordpress_Lead_Pendiente.sql` (idempotente, crea si no existe)
2. `sql/002_Producto_Generico_WP2.sql` (idempotente por CodigoLanzamiento)

## 7. Validaciones post-implementacion

### 7.1 Validar producto generico
```sql
SELECT TOP (1)
    Id,
    Nombre,
    CodigoLanzamiento,
    Estado,
    EstadoProductoTipoId,
    CostoBase
FROM adm.Producto
WHERE CodigoLanzamiento = 'PROD-GENERICO-WP2'
ORDER BY Id DESC;
```

### 7.2 Validar tabla de pendientes
```sql
SELECT OBJECT_ID('adm.Wordpress_Lead_Pendiente') AS TablaId;
```

### 7.3 Smoke test funcional recomendado
1. Enviar 1 lead nuevo al endpoint `POST /leads-generic`.
2. Esperar respuesta `201`.
3. Reenviar mismo lead (mismo email y producto).
4. Esperar respuesta `409` por dedupe.

## 8. Criterios de aprobacion
Se considera aprobado el cambio BD si:

1. Scripts ejecutados sin error en produccion.
2. Producto generico visible y activo.
3. Endpoint `POST /leads-generic` crea oportunidad (`201`).
4. Dedupe responde `409` en reintento.
5. No hay impacto negativo en flujo existente `POST /leads`.

## 9. Riesgos y mitigacion

Riesgo:
- Falta producto generico o queda inactivo.
Mitigacion:
- Verificacion automatica con query de seccion 7.1.

Riesgo:
- Permisos insuficientes del usuario de API.
Mitigacion:
- Validar grants antes del smoke test.

Riesgo:
- Desalineacion entre `GENERIC_PRODUCTO_ID` y producto real.
Mitigacion:
- Priorizar codigo de lanzamiento estable y validar variables de entorno.

## 10. Rollback
En caso de rollback de aplicacion, los cambios de BD son no destructivos.

Opciones:
- Mantener tabla `adm.Wordpress_Lead_Pendiente` (recomendado).
- Desactivar uso del endpoint `/leads-generic` en WordPress.
- Si fuera necesario, inactivar producto generico (`Estado = 0`) en lugar de borrar historial.
