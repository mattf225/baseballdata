import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

def test_supabase_connection():
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_ANON_KEY")
    
    if not url or not key:
        print("❌ Error: SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env")
        return False

    try:
        supabase: Client = create_client(url, key)
        
        # Test query to see if connection is viable
        # Attempting to fetch a row from mlb_alert_log (it should safely return an empty list if empty)
        response = supabase.table("mlb_alert_log").select("*").limit(1).execute()
        
        print("✅ Supabase Connection Successful!")
        print(f"Data returned: {response.data}")
        return True
    
    except Exception as e:
        print(f"❌ Connection failed: {str(e)}")
        return False

if __name__ == "__main__":
    print("Testing Supabase Connection...")
    test_supabase_connection()
