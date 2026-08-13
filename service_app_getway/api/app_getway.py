#!/usr/bin/env python
# -*- coding: UTF-8 -*-
from loguru import logger
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from service_app_getway.base_configs.api_config import ApiConfig
from service_app_getway.base_utils.mysql_util import SessionLocal
from service_app_getway.base_utils.ret_util import RetUtil
from service_app_getway.service.app_getway import AppGateWayService
# logger = loguru logger (auto-migrated)
#  定义超时时间，单位：秒
time_out = 30


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


api_router = APIRouter()


# 接收客户端请求并转发到后端服务
@api_router.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def gateway(service: str, path: str, request: Request, db: Session = Depends(get_db)):
    try:
        # 获取管控配置
        config_dic = AppGateWayService.get_config(db=db, config_name="power_control_service")
        ipconfig_dic = AppGateWayService.get_config(db=db, config_name="service_deployed_ip")
        keys_list = list(config_dic.keys())
        values_list = list(config_dic.values())

        # 从客户端请求中获取数据
        client_request_data = await request.json()
        url = f"{ipconfig_dic[service]}{ApiConfig.ROOT_ROUTE}/{service}/{path}"
        method = request.method
        headers = dict(request.headers)

        if service not in values_list:
            # token校验
            token_code, token_auth = AppGateWayService.verify_token(db=db, headers=headers)
            if token_auth != True:
                return RetUtil.response_error(code=token_code, message=token_auth)
            response = await AppGateWayService.request(
                method=method, url=url, client_request_data=client_request_data, time_out=time_out
            )
            return response
        else:
            index_service = values_list.index(service)
            res_name = keys_list[index_service]
            # token校验
            token_code, token_auth = AppGateWayService.verify_token(db=db, headers=headers)
            if token_auth != True:
                return RetUtil.response_error(code=token_code, message=token_auth)
            # 权限拦截器
            auth_code, auth = await AppGateWayService.verify_auth(
                db=db, headers=headers, resource_name=res_name, time_out=time_out
            )
            if auth != True:
                return RetUtil.response_error(code=auth_code, message=auth)
            # 使用 httpx 异步客户端发送请求
            response = await AppGateWayService.request(
                method=method, url=url, client_request_data=client_request_data, time_out=time_out
            )
            return response

    except Exception as e:
        detail = f"服务器错误{e}"
        logger.error("getway error: %s", detail, exc_info=True)
        # 返回HTTP错误响应
        code = RetUtil.error_code
        return RetUtil.response_error(code=code, message=detail)
