import jwt  # PyJWT library
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from models import find_user_by_account
from sanic import Sanic, response
from sanic.exceptions import Unauthorized
from sanic_ext import render
from sanic_jinja2 import SanicJinja2
from utils import (
    SECRET_KEY,
    check_password,
    generate_jwt,
    pack_admin_permission,
    pack_normal_permission,
    pack_visitor_permission,
    verify_jwt,
)

app = Sanic("auth_service")
jinja = SanicJinja2(app)

# In-memory storage for refresh tokens (You can also store them in MongoDB)
refresh_tokens = {}

# Make sure to set the template directory
app.config.TEMPLATING_PATH_TO_TEMPLATES = "./templates"


@app.middleware("response")
async def add_cors_headers(request, response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"


# Route to display the login page
@app.route("/login", methods=["GET"])
async def show_login_page(request):
    return await render("login.html")  # Render the login.html template


@app.route("/dashboard", methods=["GET"])
async def show_dashboard_page(request):
    jwt_token = request.cookies.get("auth_token")

    if not jwt_token:
        return response.redirect("/login")  # Redirect to login if no token is found

    try:
        # Decode the JWT token
        decoded_token = jwt.decode(jwt_token, SECRET_KEY, algorithms=["HS256"])
        print(decoded_token)
        allowed_routes = decoded_token.get("granted_resources", [])  # Get allowed resources from token
        print(allowed_routes)
    except (ExpiredSignatureError, InvalidTokenError):
        return response.redirect("/login")  # Redirect to login if token is invalid or expired

    # Pass the allowed routes to the template
    return jinja.render("dashboard.html", request, allowed_routes=allowed_routes)


@app.route("/grant_permission", methods=["POST"])
async def grant_permission(request):
    data = request.json
    token = data.get("token")
    decoded_token = verify_jwt(token)
    if not decoded_token:
        raise Unauthorized("Invalid token")

    # TODO: Placeholder for RBAC+ABAC policy logic to calculate granted routes
    granted_resources = {}
    if decoded_token.get("account") == "admin":
        granted_resources = pack_admin_permission()
    if decoded_token.get("account") == "normal":
        granted_resources = pack_normal_permission()
    if decoded_token.get("account") == "visitor":
        granted_resources = pack_visitor_permission()

    response_obj = response.json(
        body={
            "success": True,
            "msg": "Returning granted routes",
            "code": "000000",
            "data": {"granted_resources": granted_resources},
        }
    )
    return response_obj


@app.route("/login", methods=["POST"])
async def login(request):
    data = request.json
    account = data.get("username")
    password = data.get("password")

    print(data)

    # Find user in database
    user = find_user_by_account(account)
    if not user or not check_password(user["password"], password):
        raise Unauthorized("Invalid account or password")

    # TODO: Placeholder for RBAC+ABAC policy logic to calculate granted routes
    granted_resources = {}
    if user["account"] == "admin":
        granted_resources = pack_admin_permission()
    if user["account"] == "normal":
        granted_resources = pack_normal_permission()
    if user["account"] == "visitor":
        granted_resources = pack_visitor_permission()

    response_obj = response.json(
        body={
            "code": "000000",
            "msg": "Login success",
            "success": True,
            "data": {"token": generate_jwt({"account": account}), "granted_resources": granted_resources},
        }
    )

    # response_obj.headers["Access-Control-Allow-Origin"] = "*"
    # response_obj.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    # response_obj.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"

    # # Generate JWT token and refresh token
    # jwt_token = generate_jwt({"account": account, "granted_routes": granted_routes, "granted_resources": granted_resources})
    # refresh_token = generate_refresh_token()
    #
    # # Store refresh token with user info
    # refresh_tokens[account] = refresh_token

    # response_obj.cookies['auth_token'] = jwt_token
    # response_obj.cookies['auth_token']['httponly'] = True  # Make the cookie HTTP only for security
    # response_obj.cookies['auth_token']['max-age'] = 3600  # Set the cookie expiration time (1 hour)
    # response_obj.cookies['refresh_token'] = refresh_token
    return response_obj


@app.route("/refresh_token", methods=["POST"])
async def refresh_token(request):
    data = request.json
    account = data.get("account")
    refresh_token = data.get("refresh_token")

    # Validate refresh token
    stored_refresh_token = refresh_tokens.get(account)
    if stored_refresh_token != refresh_token:
        raise Unauthorized("Invalid refresh token")

    # Generate new JWT token
    user = find_user_by_account(account)
    granted_routes = user.get("granted_routes", [])
    new_jwt_token = generate_jwt({"account": account, "granted_routes": granted_routes})

    return response.json({"jwt_token": new_jwt_token})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9105, debug=True)
