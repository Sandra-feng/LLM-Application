import jwt
from service_app_getway.base_configs.api_config import ApiConfig
from sqlalchemy.orm import Session
from service_app_getway.model.config_model import Config_Model
from service_app_getway.base_utils.ret_util import RetUtil
from service_app_getway.model.account_token import AccountToken_Model
from service_app_getway.model.resource_model import Resource_Model
from service_app_getway.model.usr_model import Usr_Model
from base_utils.mysql_util import query2dict
import httpx
from base_utils.log_util import LogUtil
import typing

class AppGateWayService(object):
    @staticmethod
    def verify_token(db: Session, headers:dict):
        if 'account-id' not in list(headers.keys()):
            code = RetUtil.header_fail_code
            return code, "请求头Account-id不能为空"
        if not headers['account-id'] :
            code = RetUtil.header_fail_code
            return code, "请求头Account-id不能为空"
        if 'token' not in list(headers.keys()):
            code = RetUtil.header_fail_code
            return code, "请求头token不能为空"
        if not headers['token']:
            code = RetUtil.header_fail_code
            return code, "请求头token不能为空"
        account_info = db.query(AccountToken_Model).filter(AccountToken_Model.account_id == headers['account-id']).first()
        if not account_info:
            code = RetUtil.header_fail_code
            return code, "请求头Account-id不存在"

        try:
            decoded = jwt.decode(headers['token'], ApiConfig.SECRET_KEY, algorithms=["HS256"])
            token_sql = query2dict(account_info,AccountToken_Model)['token']
            if headers['token'] != token_sql:
                code = RetUtil.token_invalid_code
                return code, "token校验失败"
            code = RetUtil.success_code
            return code, True

        except jwt.ExpiredSignatureError:
            code = RetUtil.token_invalid_code
            return code, "token已过期"
        except jwt.InvalidTokenError:
            code = RetUtil.token_invalid_code
            return code, "token校验失败"

    @staticmethod
    async def verify_auth(db: Session, headers:dict,resource_name:str,time_out:int):
        try:
            config_services = AppGateWayService.get_config(db=db, config_name='service_deployed_ip')
            config_services_ip = config_services['permission-auth']

            resource_id=AppGateWayService.get_res(db=db, resource_name=resource_name)

            url = f'{config_services_ip}{ApiConfig.ROOT_ROUTE}{ApiConfig.PERMISSION_AUTH_ROUTE}/usr_auth'
            account_info = db.query(Usr_Model).filter(Usr_Model.account_id == headers['account_id']).first()
            acc_type = query2dict(account_info,Usr_Model)['attribute']
            param={'account_id':headers['account_id'],'resource_id':resource_id}
            async with httpx.AsyncClient() as client:
                response = await client.get(url=url, params=param,timeout=time_out)
            response= response.json()
            auth = response['status']

            if acc_type == 1:
                code = RetUtil.success_code
                return code,True
            if auth:
                code = RetUtil.success_code
                return code,True
            else:
                code = RetUtil.auth_fail_code
                return code, "权限校验失败"

        except Exception as e:
            detail = f"权限校验失败{e}"
            LogUtil.error(msg=detail)
            # 返回HTTP错误响应
            code = RetUtil.auth_fail_code
            return code, "权限校验失败"

    @staticmethod
    def get_res(db: Session, resource_name:str):
        res_info = db.query(Resource_Model).filter(Resource_Model.res_name == resource_name,
                                                   Resource_Model.status == 1).first()
        if res_info:
            res_id = query2dict(res_info, Resource_Model)['res_id']
            return res_id
        else:
            re = ''
            return re

    @staticmethod
    def get_config(db: Session, config_name:str):
        config_info = db.query(Config_Model).filter(Config_Model.config_name == config_name,Config_Model.status == 1).first()
        if config_info:
            config = query2dict(config_info, Config_Model)['config_description']
            return config
        else:
            re = {}
            return re

    @staticmethod
    async def request(method: str, url:str,client_request_data:typing.Any,time_out:int):
        async with httpx.AsyncClient() as client:
            if method == 'GET':
                response = await client.get(url=url, timeout=time_out)
            if method == 'POST':
                response = await client.post(url=url, json=client_request_data, timeout=time_out)
            if method == 'PUT':
                response = await client.put(url=url, json=client_request_data, timeout=time_out)
            if method == 'DELETE':
                response = await client.delete(url=url, auth=client_request_data, timeout=time_out)
            if method == 'PATCH':
                response = await client.patch(url=url, json=client_request_data, timeout=time_out)
            return response.json()


