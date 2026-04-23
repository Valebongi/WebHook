-- 002_Producto_Generico_WP2.sql
-- Crea (si no existe) un producto genérico para el endpoint /leads-generic.
--
-- Ejecutar primero en OlympusDB_QA.
-- Luego replicar en OlympusDB (producción) con los mismos valores.
--
-- Este script asume que adm.Producto tiene al menos estas columnas y que el
-- resto posee default o permite NULL.

DECLARE @Nombre              NVARCHAR(255) = N'GENERICO - Formulario WP 2';
DECLARE @CodigoLanzamiento   VARCHAR(100)  = 'PROD-GENERICO-WP2';
DECLARE @CodigoLinkedin      VARCHAR(100)  = 'GENERICO-WP2';
DECLARE @CostoBase           DECIMAL(18,2) = 0;
DECLARE @EstadoProductoTipoId INT          = 20;
DECLARE @AuditUser           NVARCHAR(100) = N'SYSTEM-WP';

IF EXISTS (
    SELECT 1
    FROM adm.Producto
    WHERE CodigoLanzamiento COLLATE DATABASE_DEFAULT = @CodigoLanzamiento COLLATE DATABASE_DEFAULT
      AND Estado = 1
)
BEGIN
    SELECT TOP (1)
        Id,
        Nombre,
        CodigoLanzamiento,
        CodigoLinkedin,
        CostoBase,
        EstadoProductoTipoId,
        Estado
    FROM adm.Producto
    WHERE CodigoLanzamiento COLLATE DATABASE_DEFAULT = @CodigoLanzamiento COLLATE DATABASE_DEFAULT
      AND Estado = 1
    ORDER BY Id DESC;

    PRINT N'Producto genérico ya existe. No se insertó una nueva fila.';
END
ELSE
BEGIN
    INSERT INTO adm.Producto
        (
            Nombre,
            CodigoLanzamiento,
            CodigoLinkedin,
            CostoBase,
            EstadoProductoTipoId,
            Estado,
            FechaCreacion,
            UsuarioCreacion,
            FechaModificacion,
            UsuarioModificacion
        )
    VALUES
        (
            @Nombre,
            @CodigoLanzamiento,
            @CodigoLinkedin,
            @CostoBase,
            @EstadoProductoTipoId,
            1,
            GETDATE(),
            @AuditUser,
            GETDATE(),
            @AuditUser
        );

    SELECT TOP (1)
        Id,
        Nombre,
        CodigoLanzamiento,
        CodigoLinkedin,
        CostoBase,
        EstadoProductoTipoId,
        Estado
    FROM adm.Producto
    WHERE CodigoLanzamiento COLLATE DATABASE_DEFAULT = @CodigoLanzamiento COLLATE DATABASE_DEFAULT
    ORDER BY Id DESC;

    PRINT N'Producto genérico creado correctamente.';
END
GO
