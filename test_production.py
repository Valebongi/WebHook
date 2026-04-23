import requests
import json

# Test payload
payload = {
    "Nombres": "Juan",
    "Apellidos": "Pérez",
    "Correo": "juan@example.com",
    "Teléfono": "+573015551234"
}

headers = {
    "X-API-Key": "GUdy2F1Foxi7DjPBUeEAoyHAas8dREN7QstceowFMbgREzIUIkqljalQS_iF376G",
    "Content-Type": "application/json"
}

url = "https://webhook-production-6be9.up.railway.app/leads-generic"

print(f"POST {url}")
print(f"Headers: {headers}")
print(f"Payload: {json.dumps(payload, indent=2)}\n")

try:
    response = requests.post(url, json=payload, headers=headers, timeout=10)
    print(f"Status: {response.status_code}")
    print(f"Response:\n{json.dumps(response.json(), indent=2)}\n")
    
    if response.status_code == 201:
        print("✅ Lead created successfully!")
        data = response.json()
        if 'oportunidad_id' in data:
            print(f"   Oportunidad ID: {data['oportunidad_id']}")
    elif response.status_code == 409:
        print("⚠️  Duplicate lead (expected on second attempt)")
    else:
        print("❌ Unexpected response")
        
except Exception as e:
    print(f"❌ ERROR: {type(e).__name__}: {e}")
