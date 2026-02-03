import sys
import os

# Add the current directory to path so we can import backend packages
sys.path.append(os.getcwd())

try:
    print("Checking imports...")
    from backend.saml.settings import get_saml_settings
    from backend.saml.auth import init_saml_auth, prepare_flask_request
    from backend.saml.routes import router
    from backend.state.history import init_history_db, get_connection
    
    print("✓ Imports Successful")
    
    print("Checking Settings Initialization...")
    settings = get_saml_settings()
    onelogin_conf = settings.to_onelogin_settings()
    
    # Basic check of critical keys
    assert "sp" in onelogin_conf
    assert "idp" in onelogin_conf
    assert "security" in onelogin_conf
    assert onelogin_conf["sp"]["entityId"]
    print("✓ Settings Configuration Valid")
    
    print("Checking DB Migration...")
    init_history_db()
    conn = get_connection()
    cursor = conn.execute("PRAGMA table_info(sessions)")
    columns = [row['name'] for row in cursor.fetchall()]
    if "user_id" in columns:
        print("✓ DB Migration Successful (user_id column exists)")
    else:
        print("❌ DB Migration FAILED (missing user_id)")
        sys.exit(1)
        
    print("\nSUCCESS: All backend SAML components are ready.")
    
except Exception as e:
    print(f"\n❌ VERIFICATION FAILED: {str(e)}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
