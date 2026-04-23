import os, pyodbc
from dotenv import load_dotenv

load_dotenv('.env')
server=os.getenv('DB_SERVER','142.93.50.164')
user=os.getenv('DB_USER','GrowthArg')
pw=os.getenv('DB_PASSWORD','')
driver=os.getenv('DB_DRIVER','ODBC Driver 17 for SQL Server')

conn_str=f'DRIVER={{{driver}}};SERVER={server};DATABASE=OlympusDB;UID={user};PWD={pw};TrustServerCertificate=yes;'
conn=pyodbc.connect(conn_str)
cur=conn.cursor()
cur.execute("SELECT Id, Nombre, CodigoLanzamiento FROM adm.Producto WHERE CodigoLanzamiento='PROD-GENERICO-WP2' AND Estado=1")
row=cur.fetchone()
if row:
    print(f'Product ID: {row[0]}')
    print(f'Nombre: {row[1]}')
    print(f'Codigo: {row[2]}')
conn.close()
