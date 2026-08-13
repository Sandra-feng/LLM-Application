import ast
import base64
import json
import time

import aioredis
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from auth_center.model.account_token import AccountToken_Model
from auth_center.model.role_mem_model import RoleMem_Model
from auth_center.model.usr_model import Usr_Model
from auth_center.utils import generate_access_token, generate_refresh_token_jwt, verify_jwt, generate_session_id
from base_utils.mysql_util import query2dict
from base_utils.redis_util import RedisUtil
from service_permission_auth.service.usr_auth_service import UsrAuthService
from service_permission_manage.service.config_service import ConfigService


class AccountAuthService:
    @staticmethod
    def query_acc_by_acc_name(db: Session, account_name: str):
        return db.query(Usr_Model).filter(Usr_Model.account_name == account_name, Usr_Model.status == 1).first()

    @staticmethod
    def query_acc_by_acc_id(db: Session, account_id: str):
        return db.query(Usr_Model).filter(Usr_Model.account_id == account_id, Usr_Model.status == 1).first()

    @staticmethod
    def query_role_by_acc_id(db: Session, account_id: str):
        return [
            item.role_id
            for item in db.query(RoleMem_Model.role_id).filter(
                RoleMem_Model.account_id == account_id, RoleMem_Model.status == 1
            )
        ]

    @staticmethod
    def local_time():
        local_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
        return local_time

    @staticmethod
    def token_access(db: Session, account_id: str):
        create_time = AccountAuthService.local_time()
        update_time = create_time

        account_info = db.query(AccountToken_Model).filter(AccountToken_Model.account_id == account_id).first()


        if not account_info:
            token = generate_access_token({"account_id": account_id})
            refresh_token = generate_refresh_token_jwt({"account_id": account_id})
            db_usr = AccountToken_Model(
                account_id=account_id,
                token=token,
                refresh_token=refresh_token,
                create_time=create_time,
                update_time=update_time,
            )
            db.add(db_usr)
            db.commit()
            db.refresh(db_usr)

        else:
            token = query2dict(account_info, AccountToken_Model)["token"]
            refresh_token = query2dict(account_info, AccountToken_Model)["refresh_token"]
            if not verify_jwt(token):
                token = generate_access_token({"account_id": account_id})
                account_info.token = token
                account_info.update_time = update_time
                db.commit()
                db.refresh(account_info)

            if not verify_jwt(refresh_token):
                refresh_token = generate_refresh_token_jwt({"account_id": account_id})
                account_info.refresh_token = refresh_token
                account_info.update_time = update_time
                db.commit()
                db.refresh(account_info)

        return token, refresh_token

    # @staticmethod
    # async def token_cache(request: Request, account_id: str, db: Session):
    #     redis = request.app.state.redis_pool
    #     account_info = await RedisUtil.get_cached_data(key=account_id, redis=redis)
    #     token_expire = await AccountAuthService.config_token_expire_seconds(db= db)
    #     if not account_info:
    #         token = generate_session_id()
    #         redis_token = await RedisUtil.cache_data(key=token, value=account_id, redis=redis, expire_seconds=token_expire)
    #     else:
    #         token = account_info["key"]
    #         redis_token = await RedisUtil.cache_data(key=token, value=account_id, redis=redis, expire_seconds=token_expire)
    #
    #     return redis_token

    @staticmethod
    async def token_cache(request: Request, account_id: str, db: Session,usr_info : dict):
        redis = request.app.state.redis_pool

        token_expire = await AccountAuthService.config_token_expire_seconds(redis=redis)

        old_token_info = await RedisUtil.get_cached_data(key=account_id, redis=redis)

        usr_json = json.dumps(usr_info, ensure_ascii=False)
        if old_token_info:
            token = old_token_info["value"]
            # 单点登录【增加这行：删除旧 session → 单点登录关键】
            # await redis.delete_cached_data(key=f"session:{token}",redis=redis
            await RedisUtil.cache_data(
                key=f"session:{token}",
                value=usr_json,
                redis=redis,
                expire_seconds=token_expire
            )
            await RedisUtil.cache_data(
            key = account_id,
            value = token,
            redis = redis,
            expire_seconds = token_expire
        )
        else:
            token = generate_session_id()
            await RedisUtil.cache_data(
                key=f"session:{token}",
                value=usr_json,
                redis=redis,
                expire_seconds=token_expire
            )
            await RedisUtil.cache_data(
                key=account_id,
                value=token,
                redis=redis,
                expire_seconds=token_expire
            )
        return token

    @staticmethod
    def decode_jwt(token):
        try:
            parts = token.split(".")
            if len(parts) != 3:
                raise HTTPException(status_code=401, detail="Token无效")
            payload = json.loads(base64.urlsafe_b64decode(parts[1] + "===").decode("utf-8"))
            account_id = payload.get("account", None)
            return account_id
        except Exception as e:
            detail = "Token无效"
            # 返回HTTP错误响应
            raise HTTPException(status_code=401, detail=detail)

    @staticmethod
    async def token_verify(request: Request, redis: aioredis.Redis, db: Session):
        url = request.url.components.path
        app_id = request.headers.get("app-id", None)
        API_Whitelist_info = await AccountAuthService.config_verify(redis=redis, db=db, keyword="API_Whitelist1")
        if not API_Whitelist_info:
            return None
        if any(keyword in url for keyword in API_Whitelist_info):
            if app_id is not None:
                account_id = UsrAuthService.get_account_by_app_id(db=db, app_id=app_id)
                if account_id == "":
                    raise HTTPException(status_code=402, detail="app_id无效")
                else:
                    request.state.account_id = account_id
                    return None

            return None
        if url == "/":
            return None
        if url.startswith("/mcp"):
            if app_id is not None:
                account_id = UsrAuthService.get_account_by_app_id(db=db, app_id=app_id)
                if account_id == "":
                    raise HTTPException(status_code=402, detail="app_id无效")
                else:
                    request.state.account_id = account_id
                    return None
        if request.url.path.startswith("/api/outside"):
            API_OutAuth_info = await AccountAuthService.config_verify(redis=redis, db=db, keyword="API_OutAuth1")
            if not API_OutAuth_info:
                raise HTTPException(status_code=403, detail="接口未授权")
            if any(keyword in url for keyword in API_OutAuth_info):
                new_path = request.url.path.replace("/api/outside", "/tc/llm/base")
                request.scope["path"] = new_path
                if app_id is not None:
                    account_id = UsrAuthService.get_account_by_app_id(db=db, app_id=app_id)
                    if account_id == "":
                        raise HTTPException(status_code=402, detail="app_id无效")
                    else:
                        request.state.account_id = account_id
                        return None
                else:
                    raise HTTPException(status_code=402, detail="app_id不能为空")
            else:
                raise HTTPException(status_code=403, detail="接口未授权")
        else:
            # token = request.headers.get("Token", None)
            # if token is not None:
            #     account_id = AccountAuthService.decode_jwt(token)
            #     account_info = await RedisUtil.get_cached_data(key=account_id, redis=redis)
            #     if not account_info:
            #         raise HTTPException(status_code=401, detail="Token已过期")
            #
            #     elif token != account_info["value"]:
            #         raise HTTPException(status_code=401, detail="Token无效")
            #
            #     else:
            #         await RedisUtil.cache_data(key=account_id, value=token, redis=redis)
            #         request.state.account_id = account_id
            #         return None
            session_id = request.headers.get("Token")
            if not session_id:
                raise HTTPException(status_code=401, detail="Token 不可为空")

            session_key = f"session:{session_id}"
            session_info = await RedisUtil.get_cached_data(key=session_key, redis=redis)
            if not session_info:
                raise HTTPException(status_code=401, detail="Session 已过期或无效")
            usr_info = json.loads(session_info["value"])
            if not usr_info:
                raise HTTPException(status_code=401, detail="Session 数据损坏或无效")
            # 单点登录【增加：判断是否是当前有效 token】
            # current_token_info = await RedisUtil.get_cached_data(
            #     key=f"user_token:{account_id}",
            #     redis=redis
            # )
            # if not current_token_info or current_token_info["value"] != session_id:
            #     raise HTTPException(status_code=401, detail="账号已在其他设备登录")
            ttl_seconds = await RedisUtil.get_ttl(key=session_key, redis=redis)
            if ttl_seconds == -2:
                raise HTTPException(status_code=401, detail="Session 不存在或已过期")
            if ttl_seconds == -1:
                ttl_seconds = 0

            REFRESH_THRESHOLD = 3600

            if ttl_seconds < REFRESH_THRESHOLD:
                token_expire = await AccountAuthService.config_token_expire_seconds(redis=redis)
                await RedisUtil.cache_data(
                    key=session_key,
                    value=json.dumps(usr_info, ensure_ascii=False),
                    redis=redis,
                    expire_seconds=token_expire
                )
                await RedisUtil.cache_data(
                    key=usr_info["account_id"],
                    value=session_id,
                    redis=redis,
                    expire_seconds=token_expire
                )
            request.state.account_id = usr_info["account_id"]
            request.state.token = session_key
            return  None

    @staticmethod
    async def config_token_expire_seconds(redis: aioredis.Redis, keyword: str="token_expire"):
        """
        从config 获取token过期时间
        :param db:
        :param keyword:
        :return:
        """
        # 获取知识溯源配置
        item_list = await RedisUtil.get_cached_data(key=keyword, redis=redis)
        if not item_list:
            raise HTTPException(status_code=500, detail=f"未查询到配置项：{keyword}")
        item = item_list["value"]
        if not item:
            raise HTTPException(status_code=500, detail="配置值为空字符串")
        try:
            expire_seconds = int(item)
        except ValueError:
            raise HTTPException(status_code=500, detail="配置值不是整数")
        if expire_seconds <= 0:
            raise HTTPException(status_code=500, detail="token_expire_seconds 配置错误")
        return expire_seconds

    @staticmethod
    async def config_cache(redis: aioredis.Redis, db: Session, keyword: str):
        configs = ConfigService.query_config_description_by_name(db, keyword)
        if configs:
            api_list = configs[0]
            return await RedisUtil.cache_data_static(key=keyword, value=str(api_list), redis=redis)
        else:
            return None

    @staticmethod
    async def config_verify(redis: aioredis.Redis, db: Session, keyword: str):
        api_config = await RedisUtil.get_cached_data(key=keyword, redis=redis)
        if not api_config:
            return None
        else:
            api_config = ast.literal_eval(api_config["value"])
            return api_config


# @staticmethod
# def generate_captcha(captcha_id: str):
#     chars = string.ascii_letters + string.digits  # 字符集（数字+字母）
#     code = ''.join(random.choices(chars, k=4))   # 随机生成4个字符
#     captcha_store[captcha_id] = code.lower()     # 保存验证码（小写）
#
#     # 图像大小
#     width, height = 120, 40
#     image = Image.new('RGB', (width, height), color=(255, 255, 255))  # 白色背景
#     draw = ImageDraw.Draw(image)
#
#     # 字体路径（更换为你本地字体文件路径）
#     font = ImageFont.truetype('arial.ttf', 32)
#
#     # 绘制验证码字符
#     for i, char in enumerate(code):
#         x = 10 + i * 25
#         y = random.randint(5, 10)
#         draw.text((x, y), char, font=font, fill=(random.randint(0, 100), random.randint(0, 100), random.randint(0, 255)))
#
#     # 添加干扰线
#     for _ in range(5):
#         x1, y1 = random.randint(0, width), random.randint(0, height)
#         x2, y2 = random.randint(0, width), random.randint(0, height)
#         draw.line((x1, y1, x2, y2), fill=(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)), width=1)
#
#     # 添加噪点
#     for _ in range(30):
#         x, y = random.randint(0, width), random.randint(0, height)
#         draw.point((x, y), fill=(0, 0, 0))
#
#     return image, code

if __name__ == "__main__":
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3MzY5NjE3NTIsImlhdCI6MTczNjkwNDE1MiwiYWNjb3VudCI6IkExODU1MDg3NDk1OTg1ODkzMzc2In0.bznU8ENX5GJIQi1xu1_uXgwzxRoi2GSTAADYeFoSoLE"
    header = AccountAuthService.decode_jwt(token)
    print(header)
