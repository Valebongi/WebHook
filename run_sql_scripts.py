import os
import pyodbc
from dotenv import load_dotenv

load_dotenv('.env')
server = os.getenv('DB_SERVER', '142.93.50.164')
user = os.getenv('DB_USER', 'GrowthArg')
pw = os.getenv('DB_PASSWORD', '')
driver = os.getenv('DB_DRIVER', 'ODBC Driver 17 for SQL Server')
db = 'OlympusDB'

print(f'Connecting to {db}...\n')

try:
    conn_str = f'DRIVER={{{driver}}};SERVER={server};DATABASE={db};UID={user};PWD={pw};TrustServerCertificate=yes;'
    conn = pyodbc.connect(conn_str, autocommit=False)
    cur = conn.cursor()
    
    # Script 1: Pending Leads Table
    print('='*70)
    print('EXECUTING: 001_Wordpress_Lead_Pendiente.sql')
    print('='*70)
    with open('sql/001_Wordpress_Lead_Pendiente.sql', 'r') as f:
        script1 = f.read()
    
    for statement in script1.split('GO'):
        if statement.strip():
            try:
                cur.execute(statement)
                print('✓ Statement executed')
            except Exception as e:
                print(f'⚠ {e}')
    
    conn.commit()
    print()

    # Script 3: Potential Applicants Table
    print('='*70)
    print('EXECUTING: 003_Wordpress_Postulante_Potencial.sql')
    print('='*70)
    with open('sql/003_Wordpress_Postulante_Potencial.sql', 'r') as f:
        script3 = f.read()

    for statement in script3.split('GO'):
        if statement.strip():
            try:
                cur.execute(statement)
                print('✓ Statement executed')
            except Exception as e:
                print(f'⚠ {e}')

    conn.commit()
    print()
    
    # Script 2: Generic Product
    print('='*70)
    print('EXECUTING: 002_Producto_Generico_WP2.sql')
    print('='*70)
    with open('sql/002_Producto_Generico_WP2.sql', 'r') as f:
        script2 = f.read()
    
    for statement in script2.split('GO'):
        if statement.strip():
            try:
                cur.execute(statement)
                print('✓ Statement executed')
            except Exception as e:
                print(f'⚠ {e}')
    
    conn.commit()
    print()
    
    # Verify
    print('='*70)
    print('VERIFICATION')
    print('='*70)
    cur.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='Wordpress_Lead_Pendiente'")
    if cur.fetchone()[0]:
        print('✓ adm.Wordpress_Lead_Pendiente exists')

    cur.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='Wordpress_Postulante_Potencial'")
    if cur.fetchone()[0]:
        print('✓ adm.Wordpress_Postulante_Potencial exists')
    
    cur.execute("SELECT COUNT(*) FROM adm.Producto WHERE CodigoLanzamiento='PROD-GENERICO-WP2' AND Estado=1")
    count = cur.fetchone()[0]
    print(f'✓ Generic product: {count} record(s)')
    
    conn.close()
    print('\nDone!')
    
except Exception as e:
    print(f'ERROR: {type(e).__name__}: {e}')
