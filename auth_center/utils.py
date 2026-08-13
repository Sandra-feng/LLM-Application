import uuid

import jwt
import bcrypt
from datetime import datetime, timedelta
import time
import hashlib


# Secret key for JWT signing
SECRET_KEY = '114514'


# Generate JWT token
def generate_jwt(user_data, expiration_minutes=30):
    expiration = datetime.now() + timedelta(minutes=expiration_minutes)
    token = jwt.encode({
        "exp": expiration,
        "iat": datetime.now(),
        "account": user_data['account_name'],
        # "granted_routes": user_data['granted_routes'],
        # "granted_resources": user_data['granted_resources']
    }, SECRET_KEY, algorithm="HS256")
    return token

def generate_access_token(user_data, expiration_minutes=960):
    expiration = datetime.now() + timedelta(minutes=expiration_minutes)
    token = jwt.encode({
        "exp": expiration,
        "iat": datetime.now(),
        "account": user_data['account_id'],
        # "granted_routes": user_data['granted_routes'],
        # "granted_resources": user_data['granted_resources']
    }, SECRET_KEY, algorithm="HS256")
    return token


def generate_session_id() -> str:
     token = uuid.uuid4().hex
     return token

def generate_refresh_token_jwt(user_data, expiration_days=7):
    expiration = datetime.now() + timedelta(days=expiration_days)
    refresh_token = jwt.encode({
        "exp": expiration,
        "account": user_data['account_id'],
    }, SECRET_KEY, algorithm="HS256")
    return refresh_token

# Generate refresh token
def generate_refresh_token():
    return bcrypt.gensalt().decode('utf-8')


# Verify JWT token
def verify_jwt(token):
    try:
        decoded = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return decoded
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# Hash and check passwords
def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def check_password(stored_password, provided_password):
    return bcrypt.checkpw(provided_password.encode('utf-8'), stored_password.encode('utf-8'))


def pack_visitor_permission():
    granted_resources = {
        'path': '/permission',
        'meta': {
            'title': '权限管理',
            'icon': 'ep:lollipop',
            'rank': 10
        },
        'children': [
            {
                'path': '/permission/page/index',
                'name': 'PermissionPage',
                'meta': {
                    'title': '页面权限',
                    'roles': ['admin', 'common']
                }
            },
            # {
            #     'path': '/permission/button',
            #     'meta': {
            #         'title': '按钮权限',
            #         'roles': ['admin', 'common']
            #     },
            #     'children': [
            #         {
            #             'path': '/permission/button/router',
            #             'component': 'permission/button/index',
            #             'name': 'PermissionButtonRouter',
            #             'meta': {
            #                 'title': '路由返回按钮权限',
            #                 'auths': ['permission:btn:add', 'permission:btn:edit', 'permission:btn:delete']
            #             }
            #         },
            #         {
            #             'path': '/permission/button/login',
            #             'component': 'permission/button/perms',
            #             'name': 'PermissionButtonLogin',
            #             'meta': {
            #                 'title': '登录接口返回按钮权限'
            #             }
            #         }
            #     ]
            # }
        ]
    }

    return granted_resources


def pack_normal_permission():
    granted_resources = {
        'path': '/permission',
        'meta': {
            'title': '权限管理',
            'icon': 'ep:lollipop',
            'rank': 10
        },
        'children': [
            {
                'path': '/permission/page/index',
                'name': 'PermissionPage',
                'meta': {
                    'title': '页面权限',
                    'roles': ['admin', 'common']
                }
            },
            {
                'path': '/permission/button',
                'meta': {
                    'title': '按钮权限',
                    'roles': ['admin', 'common']
                },
                'children': [
                    {
                        'path': '/permission/button/router',
                        'component': 'permission/button/index',
                        'name': 'PermissionButtonRouter',
                        'meta': {
                            'title': '路由返回按钮权限',
                            'auths': ['permission:btn:add', 'permission:btn:edit', 'permission:btn:delete']
                        }
                    },
                    # {
                    #     'path': '/permission/button/login',
                    #     'component': 'permission/button/perms',
                    #     'name': 'PermissionButtonLogin',
                    #     'meta': {
                    #         'title': '登录接口返回按钮权限'
                    #     }
                    # }
                ]
            }
        ]
    }

    return granted_resources


def pack_admin_permission():
    granted_resources = {
        'path': '/permission',
        'meta': {
            'title': '权限管理',
            'icon': 'ep:lollipop',
            'rank': 10
        },
        'children': [
            {
                'path': '/permission/page/index',
                'name': 'PermissionPage',
                'meta': {
                    'title': '页面权限',
                    'roles': ['admin', 'common']
                }
            },
            {
                'path': '/permission/button',
                'meta': {
                    'title': '按钮权限',
                    'roles': ['admin', 'common']
                },
                'children': [
                    {
                        'path': '/permission/button/router',
                        'component': 'permission/button/index',
                        'name': 'PermissionButtonRouter',
                        'meta': {
                            'title': '路由返回按钮权限',
                            'auths': ['permission:btn:add', 'permission:btn:edit', 'permission:btn:delete']
                        }
                    },
                    {
                        'path': '/permission/button/login',
                        'component': 'permission/button/perms',
                        'name': 'PermissionButtonLogin',
                        'meta': {
                            'title': '登录接口返回按钮权限'
                        }
                    }
                ]
            }
        ]
    }

    return granted_resources

def md5(arg):
    # 将数据转换成UTF-8格式
    se = hashlib.md5(arg.encode('utf-8'))
    # 将hash中的数据转换成只包含十六进制的数字
    result = se.hexdigest()
    return result

if __name__ == "__main__":
    # hashed = hash_password('adminpwd')
    # print(bcrypt.checkpw('adminpwd'.encode('utf-8'), hashed.encode('utf-8')))

    user_data={'account_name':'usr'}
    token = generate_jwt(user_data)
    print(token)
    current_timestamp = int(time.time())
    print(current_timestamp)
