#!/usr/bin/env python3
"""
Castle Bot - API Key Verification Script
Tests all configured API keys to ensure they're valid and working.

LLM ROLE ASSIGNMENT:
- Claude (Anthropic): Code Generation & Self-Improvement (PRIMARY)
- Gemini (Google): Market Sentiment & News Analysis
- OpenAI (GPT-4): Technical Analysis & Risk Assessment
"""

import os
import sys
import json
import base64
from pathlib import Path
from datetime import datetime, timezone

# Colors for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'

def print_header(text):
    print(f"\n{BOLD}{BLUE}{'='*60}{RESET}")
    print(f"{BOLD}{BLUE}{text}{RESET}")
    print(f"{BOLD}{BLUE}{'='*60}{RESET}\n")

def print_success(text):
    print(f"{GREEN}✓ {text}{RESET}")

def print_error(text):
    print(f"{RED}✗ {text}{RESET}")

def print_warning(text):
    print(f"{YELLOW}⚠ {text}{RESET}")

def print_info(text):
    print(f"{BLUE}ℹ {text}{RESET}")

def load_env():
    """Load environment variables from .env file"""
    env_path = Path('.env')
    if not env_path.exists():
        print_error(".env file not found!")
        print_info("Create it with: cp env.example .env")
        return False
    
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, value = line.partition('=')
                os.environ[key.strip()] = value.strip()
    
    print_success(".env file loaded")
    return True

def check_kalshi_api():
    """Test Kalshi API credentials using direct authentication"""
    print_header("1. KALSHI API")
    
    key_id = os.getenv('KALSHI_API_KEY_ID', '').strip()
    pk_path = os.getenv('KALSHI_PRIVATE_KEY_PATH', '').strip()
    kalshi_env = os.getenv('KALSHI_ENV', 'demo').strip()
    
    if not key_id:
        print_error("KALSHI_API_KEY_ID not set")
        return False
    
    if key_id.startswith('your-') or key_id == '':
        print_error("KALSHI_API_KEY_ID is placeholder value")
        return False
    
    print_success(f"KALSHI_API_KEY_ID: {key_id[:8]}...{key_id[-4:]}")
    
    if not pk_path:
        print_error("KALSHI_PRIVATE_KEY_PATH not set")
        return False
    
    pk_file = Path(pk_path)
    if not pk_file.exists():
        print_error(f"Private key file not found: {pk_path}")
        return False
    
    print_success(f"Private key file exists: {pk_path}")
    print_info(f"Environment: {kalshi_env}")
    
    # Test public endpoint first
    try:
        import requests
        
        if kalshi_env == 'demo':
            base_url = "https://demo-api.kalshi.co/trade-api/v2"
        else:
            base_url = "https://api.elections.kalshi.com/trade-api/v2"
        
        print_info("Testing market fetch (public endpoint)...")
        response = requests.get(f"{base_url}/markets?limit=5&status=open", timeout=10)
        
        if response.status_code == 200:
            markets = response.json().get('markets', [])
            print_success(f"Fetched {len(markets)} markets successfully")
        else:
            print_error(f"Public endpoint failed: {response.status_code}")
            return False
            
    except Exception as e:
        print_error(f"Public endpoint error: {e}")
        return False
    
    # Test authenticated endpoint
    try:
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        
        # Load private key
        with open(pk_path, 'rb') as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
        
        print_info("Testing authenticated endpoint (balance)...")
        
        # Generate signature
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
        
        url = f"{base_url}/portfolio/balance"
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            balance_data = response.json()
            balance_cents = balance_data.get('balance', 0)
            portfolio_value = balance_data.get('portfolio_value', 0)
            print_success(f"Balance: ${balance_cents/100:.2f}")
            print_success(f"Portfolio value: ${portfolio_value/100:.2f}")
            return True
        else:
            print_error(f"Authentication failed: {response.status_code}")
            print_error(f"Response: {response.text[:200]}")
            return False
            
    except ImportError as e:
        print_error(f"Missing dependency: {e}")
        print_info("Install with: pip install cryptography requests")
        return False
    except Exception as e:
        print_error(f"Authentication test failed: {e}")
        return False

def check_anthropic_api():
    """Test Anthropic (Claude) API key - PRIMARY for code generation"""
    print_header("2. ANTHROPIC API (Claude) - CODE GENERATION")
    
    api_key = os.getenv('ANTHROPIC_API_KEY', '').strip()
    
    if not api_key:
        print_error("ANTHROPIC_API_KEY not set")
        print_info("Required for code generation & self-improvement")
        print_info("Get your key at: https://console.anthropic.com/settings/keys")
        return False
    
    if api_key.startswith('your-') or api_key == '':
        print_error("ANTHROPIC_API_KEY is placeholder value")
        return False
    
    print_success(f"ANTHROPIC_API_KEY: {api_key[:10]}...{api_key[-4:]}")
    print_info("Role: Code generation & self-improvement (PRIMARY)")
    
    try:
        import requests
        
        headers = {
            'x-api-key': api_key,
            'Content-Type': 'application/json',
            'anthropic-version': '2023-06-01'
        }
        
        print_info("Testing API connection...")
        response = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers=headers,
            json={
                'model': 'claude-3-haiku-20240307',
                'max_tokens': 10,
                'messages': [{'role': 'user', 'content': 'Hi'}]
            },
            timeout=15
        )
        
        if response.status_code == 200:
            print_success("API key valid! Claude is responding")
            print_success("Ready for code generation & improvement proposals")
            return True
        elif response.status_code == 401:
            print_error("Invalid API key (401 Unauthorized)")
            return False
        elif response.status_code == 429:
            print_warning("Rate limited (429) - key is valid but quota exceeded")
            return True
        else:
            print_error(f"API error: {response.status_code} - {response.text[:100]}")
            return False
            
    except Exception as e:
        print_error(f"Anthropic API test failed: {e}")
        return False

def check_gemini_api():
    """Test Google Gemini API key - Market sentiment analysis"""
    print_header("3. GEMINI API (Google) - MARKET SENTIMENT")
    
    api_key = os.getenv('GEMINI_API_KEY', '').strip()
    model = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash').strip()
    
    if not api_key:
        print_warning("GEMINI_API_KEY not set")
        print_info("Used for market sentiment & news analysis")
        return None
    
    if api_key.startswith('your-') or api_key == '':
        print_error("GEMINI_API_KEY is placeholder value")
        return False
    
    print_success(f"GEMINI_API_KEY: {api_key[:10]}...{api_key[-4:]}")
    print_info(f"Model: {model}")
    print_info("Role: Market sentiment & news analysis")
    
    try:
        import requests
        
        print_info("Testing API connection...")
        response = requests.get(
            f'https://generativelanguage.googleapis.com/v1beta/models?key={api_key}',
            timeout=10
        )
        
        if response.status_code == 200:
            models = response.json().get('models', [])
            print_success(f"API key valid! Found {len(models)} models")
            print_success("Ready for market sentiment analysis")
            return True
        else:
            print_error(f"API error: {response.status_code}")
            return False
            
    except Exception as e:
        print_error(f"Gemini API test failed: {e}")
        return False

def check_openai_api():
    """Test OpenAI API key - Technical analysis"""
    print_header("4. OPENAI API (GPT-4) - TECHNICAL ANALYSIS")
    
    api_key = os.getenv('OPENAI_API_KEY', '').strip()
    model = os.getenv('OPENAI_MODEL', 'gpt-4o').strip()
    
    if not api_key:
        print_warning("OPENAI_API_KEY not set")
        print_info("Used for technical analysis & risk assessment")
        return None
    
    if api_key.startswith('your-') or api_key == '':
        print_error("OPENAI_API_KEY is placeholder value")
        return False
    
    print_success(f"OPENAI_API_KEY: {api_key[:7]}...{api_key[-4:]}")
    print_info(f"Model: {model}")
    print_info("Role: Technical analysis & risk assessment")
    
    try:
        import requests
        
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        print_info("Testing API connection...")
        response = requests.get(
            'https://api.openai.com/v1/models',
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            models = response.json().get('data', [])
            print_success(f"API key valid! Found {len(models)} models")
            
            model_ids = [m['id'] for m in models]
            if model in model_ids or any(model in m for m in model_ids):
                print_success(f"Model '{model}' is available")
            
            print_success("Ready for technical analysis")
            return True
        elif response.status_code == 401:
            print_error("Invalid API key (401 Unauthorized)")
            return False
        else:
            print_error(f"API error: {response.status_code}")
            return False
            
    except Exception as e:
        print_error(f"OpenAI API test failed: {e}")
        return False

def check_newsapi():
    """Test NewsAPI key"""
    print_header("5. NEWSAPI - NEWS INTEGRATION")
    
    api_key = os.getenv('NEWS_API_KEY', '').strip()
    
    if not api_key:
        print_warning("NEWS_API_KEY not set (optional)")
        return None
    
    print_success(f"NEWS_API_KEY: {api_key[:8]}...{api_key[-4:]}")
    
    try:
        import requests
        
        print_info("Testing API connection...")
        response = requests.get(
            'https://newsapi.org/v2/top-headlines',
            params={'country': 'us', 'pageSize': 1},
            headers={'X-Api-Key': api_key},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            total = data.get('totalResults', 0)
            print_success(f"API key valid! {total} articles available")
            return True
        else:
            print_error(f"API error: {response.status_code}")
            return False
            
    except Exception as e:
        print_error(f"NewsAPI test failed: {e}")
        return False

def check_polygon_api():
    """Test Polygon.io API key"""
    print_header("6. POLYGON API - FINANCIAL DATA")
    
    api_key = os.getenv('POLYGON_API_KEY', '').strip()
    
    if not api_key:
        print_info("POLYGON_API_KEY not set (optional)")
        return None
    
    print_success(f"POLYGON_API_KEY: {api_key[:8]}...{api_key[-4:]}")
    
    try:
        import requests
        
        print_info("Testing API connection...")
        response = requests.get(
            f'https://api.polygon.io/v2/aggs/ticker/AAPL/prev',
            params={'apiKey': api_key},
            timeout=10
        )
        
        if response.status_code == 200:
            print_success("API key valid!")
            return True
        else:
            print_error(f"API error: {response.status_code}")
            return False
            
    except Exception as e:
        print_error(f"Polygon API test failed: {e}")
        return False

def print_summary(results):
    """Print summary of all API checks"""
    print_header("SUMMARY")
    
    status_map = {
        True: f"{GREEN}✓ Working{RESET}",
        False: f"{RED}✗ Failed{RESET}",
        None: f"{YELLOW}○ Not configured{RESET}"
    }
    
    print(f"{'Service':<20} {'Status':<20} {'Role':<25}")
    print("-" * 65)
    
    services = [
        ('Kalshi', results.get('kalshi'), 'Trading (REQUIRED)'),
        ('Anthropic/Claude', results.get('anthropic'), 'Code Generation'),
        ('Gemini', results.get('gemini'), 'Market Sentiment'),
        ('OpenAI/GPT-4', results.get('openai'), 'Technical Analysis'),
        ('NewsAPI', results.get('newsapi'), 'News (Optional)'),
        ('Polygon', results.get('polygon'), 'Financial (Optional)'),
    ]
    
    for name, status, role in services:
        print(f"{name:<20} {status_map[status]:<30} {role:<25}")
    
    print()
    
    # Check codegen provider
    codegen_provider = os.getenv('CODEGEN_PROVIDER', 'anthropic').lower()
    print(f"{BOLD}Code Generation Provider:{RESET} {codegen_provider.upper()}")
    
    if codegen_provider == 'anthropic' and results.get('anthropic'):
        print_success("Claude is ready for code generation")
    elif codegen_provider == 'openai' and results.get('openai'):
        print_warning("Using OpenAI for codegen (consider switching to Claude)")
        print_info("Set CODEGEN_PROVIDER=anthropic in .env")
    elif codegen_provider == 'anthropic' and not results.get('anthropic'):
        print_error("Claude not available but set as codegen provider!")
    
    print()
    
    # Overall status
    kalshi_ok = results.get('kalshi') == True
    codegen_ok = results.get('anthropic') == True
    strategy_ok = (results.get('gemini') == True or results.get('openai') == True)
    
    if kalshi_ok and codegen_ok and strategy_ok:
        print_success("🎉 All systems ready for autonomous trading!")
    elif kalshi_ok and codegen_ok:
        print_success("Ready for trading with code generation")
        if not strategy_ok:
            print_warning("Multi-LLM strategy consensus not fully available")
    elif kalshi_ok:
        print_success("Ready for basic trading (paper/demo/prod modes)")
        if not codegen_ok:
            print_warning("Code generation disabled (no Claude API key)")
    else:
        print_error("Kalshi API not working - cannot trade")

def main():
    print(f"\n{BOLD}Castle Bot - API Key Verification{RESET}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    if not load_env():
        sys.exit(1)
    
    results = {}
    
    results['kalshi'] = check_kalshi_api()
    results['anthropic'] = check_anthropic_api()
    results['gemini'] = check_gemini_api()
    results['openai'] = check_openai_api()
    results['newsapi'] = check_newsapi()
    results['polygon'] = check_polygon_api()
    
    print_summary(results)
    
    if results.get('kalshi') == True:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == '__main__':
    main()
