-- 001_Wordpress_Lead_Pendiente.sql
-- Tabla donde caen los leads de WordPress que NO se pudieron procesar
-- automáticamente (sin match de producto, teléfono inválido, etc.).
--
-- Ejecutar PRIMERO en OlympusDB_QA para testing. Una vez validado,
-- ejecutar también en OlympusDB para producción.
--
-- USO típico:
--   SELECT * FROM adm.Wordpress_Lead_Pendiente
--   WHERE Estado = 0      -- 0=pendiente, 1=resuelto, 2=descartado
--   ORDER BY FechaCreacion DESC;

IF NOT EXISTS (
    SELECT 1 FROM sys.tables t
    INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
    WHERE s.name = 'adm' AND t.name = 'Wordpress_Lead_Pendiente'
)
BEGIN
    CREATE TABLE [adm].[Wordpress_Lead_Pendiente] (
        [Id]                    INT           IDENTITY(1,1) NOT NULL,
        [NombreCapacitacion]    NVARCHAR(300) NOT NULL,
        [Nombres]               NVARCHAR(255) NULL,
        [Apellidos]             NVARCHAR(255) NULL,
        [Email]                 NVARCHAR(255) NOT NULL,
        [Telefono]              NVARCHAR(40)  NOT NULL,    -- el valor crudo recibido
        [IdPais]                INT           NULL,
        [CodigoPais]            VARCHAR(20)   NULL,        -- "+57"
        [Celular]               VARCHAR(50)   NULL,        -- parte local del teléfono
        [FormId]                INT           NULL,
        [FechaFormulario]       DATETIME      NULL,
        [MotivoPendiente]       NVARCHAR(300) NOT NULL,    -- por qué quedó pendiente
        [Estado]                TINYINT       NOT NULL
            CONSTRAINT [DF_WpLeadPendiente_Estado] DEFAULT (0), -- 0=pendiente 1=resuelto 2=descartado
        [OportunidadId]         INT           NULL,        -- se setea si luego se resuelve manualmente
        [Observacion]           NVARCHAR(1000) NULL,        -- notas de quien lo revisa
        [FechaCreacion]         DATETIME      NOT NULL
            CONSTRAINT [DF_WpLeadPendiente_FechaCreacion] DEFAULT (GETDATE()),
        [UsuarioCreacion]       NVARCHAR(100) NOT NULL
            CONSTRAINT [DF_WpLeadPendiente_UsuarioCreacion] DEFAULT (N'SYSTEM-WP'),
        [FechaModificacion]     DATETIME      NOT NULL
            CONSTRAINT [DF_WpLeadPendiente_FechaModificacion] DEFAULT (GETDATE()),
        [UsuarioModificacion]   NVARCHAR(100) NOT NULL
            CONSTRAINT [DF_WpLeadPendiente_UsuarioModificacion] DEFAULT (N'SYSTEM-WP'),
        CONSTRAINT [PK_Wordpress_Lead_Pendiente] PRIMARY KEY CLUSTERED ([Id])
    );

    CREATE NONCLUSTERED INDEX [IX_WpLeadPendiente_Estado]
        ON [adm].[Wordpress_Lead_Pendiente] ([Estado], [FechaCreacion] DESC);

    CREATE NONCLUSTERED INDEX [IX_WpLeadPendiente_Email]
        ON [adm].[Wordpress_Lead_Pendiente] ([Email]);

    PRINT N'Tabla adm.Wordpress_Lead_Pendiente creada.';
END
ELSE
BEGIN
    PRINT N'Tabla adm.Wordpress_Lead_Pendiente ya existe, no se realizó ninguna acción.';
END
GO
