-- 003_Wordpress_Postulante_Potencial.sql
-- Tabla para almacenar postulantes potenciales provenientes de formulario web.
--
-- Ejecutar primero en OlympusDB_QA para validación y luego en OlympusDB.
--
-- Estado sugerido:
--   0 = pendiente_contacto
--   1 = contactado
--   2 = en_proceso
--   3 = contratado
--   4 = no_seleccionado

IF NOT EXISTS (
    SELECT 1
    FROM sys.tables t
    INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
    WHERE s.name = 'adm' AND t.name = 'Wordpress_Postulante_Potencial'
)
BEGIN
    CREATE TABLE [adm].[Wordpress_Postulante_Potencial] (
        [Id]                    INT             IDENTITY(1,1) NOT NULL,
        [NombreCompleto]        NVARCHAR(255)   NOT NULL,
        [CorreoElectronico]     NVARCHAR(255)   NOT NULL,
        [AreaPostulacion]       NVARCHAR(150)   NOT NULL,
        [CvNombreArchivo]       NVARCHAR(260)   NULL,
        [CvMimeType]            VARCHAR(100)    NULL,
        [CvContenido]           VARBINARY(MAX)  NULL,
        [CvTamanoBytes]         INT             NULL,
        [Estado]                TINYINT         NOT NULL
            CONSTRAINT [DF_WpPostulante_Estado] DEFAULT (0),
        [Observacion]           NVARCHAR(1000)  NULL,
        [FechaPostulacion]      DATETIME        NOT NULL
            CONSTRAINT [DF_WpPostulante_FechaPostulacion] DEFAULT (GETDATE()),
        [FechaCreacion]         DATETIME        NOT NULL
            CONSTRAINT [DF_WpPostulante_FechaCreacion] DEFAULT (GETDATE()),
        [UsuarioCreacion]       NVARCHAR(100)   NOT NULL
            CONSTRAINT [DF_WpPostulante_UsuarioCreacion] DEFAULT (N'SYSTEM-WP'),
        [FechaModificacion]     DATETIME        NOT NULL
            CONSTRAINT [DF_WpPostulante_FechaModificacion] DEFAULT (GETDATE()),
        [UsuarioModificacion]   NVARCHAR(100)   NOT NULL
            CONSTRAINT [DF_WpPostulante_UsuarioModificacion] DEFAULT (N'SYSTEM-WP'),
        CONSTRAINT [PK_Wordpress_Postulante_Potencial] PRIMARY KEY CLUSTERED ([Id])
    );

    CREATE NONCLUSTERED INDEX [IX_WpPostulante_Estado_Fecha]
        ON [adm].[Wordpress_Postulante_Potencial] ([Estado], [FechaPostulacion] DESC);

    CREATE NONCLUSTERED INDEX [IX_WpPostulante_Correo]
        ON [adm].[Wordpress_Postulante_Potencial] ([CorreoElectronico]);

    PRINT N'Tabla adm.Wordpress_Postulante_Potencial creada.';
END
ELSE
BEGIN
    PRINT N'Tabla adm.Wordpress_Postulante_Potencial ya existe, no se realizó ninguna acción.';
END
GO
