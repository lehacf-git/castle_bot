#!/usr/bin/env python3
"""
Kalshi Authentication Debug Script
Diagnoses why authentication is failing.
"""

import os
import sys
import base64
import hashlib
from pathlib import Path
from datetime import datetime, timezone

def load_env():
    """Load .env file"""
    env_path = Path('.env')
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    os.environ[key.strip()] = value.strip()

def main():
    print("=" * 60)
    print("KALSHI AUTHENTICATION DEBUG")
    print("=" * 60)
    
    load_env()
    
    key_id = os.getenv('KALSHI_API_KEY_ID', '').strip()
    pk_path = os.getenv('KALSHI_PRIVATE_KEY_PATH', '').strip()
    kalshi_env = os.getenv('KALSHI_ENV', 'demo').strip()
    
    print(f"\n1. Configuration:")
    print(f"   KALSHI_ENV: {kalshi_env}")
    print(f"   KALSHI_API_KEY_ID: {key_id}")
    print(f"   KALSHI_PRIVATE_KEY_PATH: {pk_path}")
    
    # Check .env for any issues
    print(f"\n2. Checking .env file...")
    with open('.env', 'r') as f:
        env_content = f.read()
    
    # Look for the key ID in .env
    if key_id in env_content:
        print(f"   ✓ Key ID found in .env")
    else:
        print(f"   ✗ Key ID NOT found in .env - check for typos!")
    
    # Check for quotes or extra spaces
    for line in env_content.split('\n'):
        if 'KALSHI_API_KEY_ID' in line:
            print(f"   Raw line: '{line}'")
            if '"' in line or "'" in line:
                print(f"   ⚠ WARNING: Found quotes in value - remove them!")
            if line.endswith(' '):
                print(f"   ⚠ WARNING: Trailing space detected!")
    
    # Load and check private key
    print(f"\n3. Checking private key file...")
    pk_file = Path(pk_path)
    
    if not pk_file.exists():
        print(f"   ✗ File not found: {pk_path}")
        return
    
    with open(pk_file, 'rb') as f:
        pk_content = f.read()
    
    print(f"   File size: {len(pk_content)} bytes")
    print(f"   File modified: {datetime.fromtimestamp(pk_file.stat().st_mtime)}")
    
    # Check PEM format
    pk_text = pk_content.decode('utf-8', errors='replace')
    lines = pk_text.strip().split('\n')
    
    print(f"   First line: {lines[0]}")
    print(f"   Last line: {lines[-1]}")
    print(f"   Total lines: {len(lines)}")
    
    if 'BEGIN RSA PRIVATE KEY' in lines[0]:
        print(f"   ✓ Valid RSA private key format")
    elif 'BEGIN PRIVATE KEY' in lines[0]:
        print(f"   ✓ Valid PKCS8 private key format")
    else:
        print(f"   ✗ Invalid private key format!")
        return
    
    # Try to load the key
    print(f"\n4. Loading private key...")
    try:
        from cryptography.hazmat.primitives import serialization
        
        private_key = serialization.load_pem_private_key(
            pk_content,
            password=None
        )
        print(f"   ✓ Private key loaded successfully")
        print(f"   Key size: {private_key.key_size} bits")
    except Exception as e:
        print(f"   ✗ Failed to load private key: {e}")
        return
    
    # Test signature generation
    print(f"\n5. Testing signature generation...")
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        
        timestamp = str(int(datetime.now(timezone.utc).timestamp() * 1000))
        method = "GET"
        path = "/trade-api/v2/portfolio/balance"
        
        message = f"{timestamp}{method}{path}"
        print(f"   Message to sign: {message[:50]}...")
        
        signature = private_key.sign(
            message.encode('utf-8'),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        
        sig_b64 = base64.b64encode(signature).decode('utf-8')
        print(f"   ✓ Signature generated: {sig_b64[:30]}...")
        
    except Exception as e:
        print(f"   ✗ Signature generation failed: {e}")
        return
    
    # Make actual API call with verbose output
    print(f"\n6. Making authenticated API call...")
    try:
        import requests
        
        if kalshi_env == 'demo':
            base_url = "https://demo-api.kalshi.co/trade-api/v2"
        else:
            base_url = "https://api.elections.kalshi.com/trade-api/v2"
        
        url = f"{base_url}/portfolio/balance"
        
        # Generate fresh signature
        timestamp = str(int(datetime.now(timezone.utc).timestamp() * 1000))
        path = "/trade-api/v2/portfolio/balance"
        message = f"{timestamp}GET{path}"
        
        signature = private_key.sign(
            message.encode('utf-8'),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        sig_b64 = base64.b64encode(signature).decode('utf-8')
        
        headers = {
            "KALSHI-ACCESS-KEY": key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": sig_b64,
            "Content-Type": "application/json",
        }
        
        print(f"   URL: {url}")
        print(f"   Headers:")
        print(f"     KALSHI-ACCESS-KEY: {key_id}")
        print(f"     KALSHI-ACCESS-TIMESTAMP: {timestamp}")
        print(f"     KALSHI-ACCESS-SIGNATURE: {sig_b64[:30]}...")
        
        response = requests.get(url, headers=headers, timeout=10)
        
        print(f"\n   Response status: {response.status_code}")
        print(f"   Response body: {response.text[:200]}")
        
        if response.status_code == 200:
            print(f"\n   ✓ SUCCESS! Authentication working!")
            balance = response.json()
            print(f"   Balance: ${balance.get('balance', 0)/100:.2f}")
        else:
            print(f"\n   ✗ Authentication failed")
            
            # Additional diagnostics
            if 'INCORRECT_API_KEY_SIGNATURE' in response.text:
                print(f"\n   DIAGNOSIS: Signature mismatch")
                print(f"   Possible causes:")
                print(f"   1. The .pem file doesn't match this API key ID")
                print(f"   2. The API key was regenerated but old .pem is being used")
                print(f"   3. There's a character encoding issue in the .pem file")
                
                print(f"\n   SOLUTION:")
                print(f"   1. Delete API key '{key_id[:8]}...' on Kalshi")
                print(f"   2. Create a brand new API key")
                print(f"   3. IMMEDIATELY download the new .pem file")
                print(f"   4. Save it to: {pk_path}")
                print(f"   5. Update KALSHI_API_KEY_ID in .env")
            
    except Exception as e:
        print(f"   ✗ API call failed: {e}")
    
    print("\n" + "=" * 60)

if __name__ == '__main__':
    main()
