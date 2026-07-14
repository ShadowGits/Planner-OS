import os
import jwt
import urllib.parse
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Form, Query, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

oauth_router = APIRouter(tags=["OAuth Proxy"])

@oauth_router.get("/authorize", response_class=HTMLResponse)
@oauth_router.get("/api/oauth/authorize", response_class=HTMLResponse)
async def authorize_form(
    request: Request,
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    response_type: str = Query(default="code"),
    state: str = Query(default=""),
    code_challenge: str = Query(default=""),
    code_challenge_method: str = Query(default=""),
):
    """Serve a simple HTML form to collect the MCP_API_KEY."""
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Connect to Planner OS</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background-color: #f5f5f5; }}
            .container {{ background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); max-width: 400px; width: 100%; text-align: center; }}
            h2 {{ margin-top: 0; }}
            input[type="password"] {{ width: 100%; padding: 10px; margin: 15px 0; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }}
            button {{ background: #000; color: #fff; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; width: 100%; font-size: 16px; }}
            button:hover {{ background: #333; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Planner OS Auth</h2>
            <p>Please enter your <strong>MCP_API_KEY</strong> to authorize Claude.</p>
            <form action="/authorize" method="POST">
                <input type="hidden" name="client_id" value="{client_id}">
                <input type="hidden" name="redirect_uri" value="{redirect_uri}">
                <input type="hidden" name="state" value="{state}">
                
                <input type="password" name="api_key" placeholder="MCP_API_KEY" required>
                <button type="submit">Authorize Claude</button>
            </form>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@oauth_router.post("/authorize", response_class=RedirectResponse)
@oauth_router.post("/api/oauth/authorize", response_class=RedirectResponse)
async def authorize_submit(
    api_key: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    state: str = Form(default=""),
):
    """Validate the key and redirect back to Claude with a JWT code."""
    expected_key = os.environ.get("MCP_API_KEY")
    if not expected_key or api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API Key")

    # Generate a short-lived JWT as the authorization code
    payload = {
        "client_id": client_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        "iat": datetime.now(timezone.utc)
    }
    # Sign it with the MCP_API_KEY itself, so only we can decode it
    code = jwt.encode(payload, expected_key, algorithm="HS256")

    # Build redirect URL
    redirect_params = {"code": code}
    if state:
        redirect_params["state"] = state
    
    query_string = urllib.parse.urlencode(redirect_params)
    url = f"{redirect_uri}?{query_string}"
    
    return RedirectResponse(url=url, status_code=303)


@oauth_router.post("/token")
@oauth_router.post("/api/oauth/token")
async def exchange_token(request: Request):
    """Exchange the JWT code for the actual MCP_API_KEY."""
    expected_key = os.environ.get("MCP_API_KEY")
    if not expected_key:
        raise HTTPException(status_code=500, detail="Server missing MCP_API_KEY")
        
    grant_type = None
    code = None
    
    try:
        form = await request.form()
        grant_type = form.get("grant_type")
        code = form.get("code")
    except:
        pass
        
    if not grant_type:
        try:
            body = await request.json()
            grant_type = body.get("grant_type")
            code = body.get("code")
        except:
            pass

    if grant_type == "refresh_token":
        pass
    elif grant_type == "authorization_code":
        if not code:
            raise HTTPException(status_code=400, detail="Missing code")
        try:
            # Verify the code was signed by us
            payload = jwt.decode(code, expected_key, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=400, detail="Code expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=400, detail="Invalid code")
    else:
        # If Claude doesn't send a standard grant_type for some reason, just succeed anyway if we have a code
        if code:
            try:
                payload = jwt.decode(code, expected_key, algorithms=["HS256"])
            except:
                raise HTTPException(status_code=400, detail="Invalid code")

    # If valid, return the actual MCP_API_KEY as the access token!
    # Claude will now pass this token in the Authorization: Bearer header.
    return JSONResponse({
        "access_token": expected_key,
        "token_type": "bearer",
        "expires_in": 31536000,  # 1 year
        "refresh_token": "dummy_refresh_token" # Satisfy OAuth clients that expect it
    })
