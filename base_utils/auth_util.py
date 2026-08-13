import jwt
import time
import json
from functools import wraps
from sanic import response
import requests



def protected_route(auth_service_url):
    def decorator(f):
        @wraps(f)
        async def decorated_function(request, *args, **kwargs):
            # 1. Check if the request has a cookie containing the JWT token
            account = request.cookies.get('account')
            jwt_token = request.cookies.get(f'{account}_jwt_token')

            if not jwt_token:
                return response.redirect('/login')

            try:
                # 2. Decode the JWT token and check if it is expired or invalid
                payload = jwt.decode(jwt_token, options={"verify_signature": False})
                exp = payload.get('exp')
                if time.time() > exp:
                    return response.redirect('/login')  # Token is expired, redirect to login

                # 3. Check if the token is about to expire (e.g., less than 5 minutes remaining)
                if exp - time.time() < 300:  # Less than 5 minutes
                    refresh_token = request.cookies.get(f'{account}_refresh_token')
                    if refresh_token:
                        new_token, new_refresh_token = refresh_jwt_token(auth_service_url, refresh_token)
                        if new_token:
                            # Update the token in the cookie
                            response.cookies[f'{account}_jwt_token'] = new_token
                            response.cookies[f'{account}_refresh_token'] = new_refresh_token
                            jwt_token = new_token  # Use the new token for subsequent checks
                        else:
                            return response.redirect('/login')  # Refresh failed, redirect to login
                    else:
                        return response.redirect('/login')  # No refresh token, redirect to login

                # 4. Check the granted route list stored in the token
                granted_routes = payload.get('granted_routes', [])
                current_route = request.path

                if current_route in granted_routes:
                    return await f(request, *args, **kwargs)  # Token is valid, route is allowed
                else:
                    return response.json({'message': 'Access denied. You do not have permission to access this route.'}, status=403)

            except jwt.ExpiredSignatureError:
                return response.redirect('/login')  # Token is expired, redirect to login
            except jwt.InvalidTokenError:
                return response.redirect('/login')  # Token is invalid, redirect to login

        return decorated_function

    return decorator


def refresh_jwt_token(auth_service_url, refresh_token):
    # Call auth service to get a new token using the refresh token
    response = requests.post(f"{auth_service_url}/oauth/token", json={
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token
    })

    if response.status_code == 200:
        data = response.json()
        return data.get('access_token'), data.get('refresh_token')
    else:
        return None, None


if __name__ == "__main__":
    print("refresh_token")
