#!/usr/bin/env python
# -*- coding: UTF-8 -*-
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from loguru import logger
from sqlalchemy.orm import Session

from auth_center.entity.account_entity import AccountEntityNew, ULoginEntity, URegisterEntity
from auth_center.model.usr_model import Usr_Model
from auth_center.service.auth_service import AccountAuthService
from auth_center.utils import md5
from base_utils.mysql_util import query2dict
from base_utils.ret_util import RetUtil
from base_utils.sm2 import sm2decrypt
from service_permission_auth.entity.usr_auth_entity import UsrEntity
from service_permission_auth.service.usr_auth_service import UsrAuthService

# logger = loguru logger (auto-migrated)
router = APIRouter()


def get_db(request: Request):
    db = request.app.state.SessionLocal()
    try:
        yield db
    finally:
        db.close()


api_router = APIRouter()


@api_router.post("/token/access", summary="Token获取", response_model=AccountEntityNew)
async def login(request: Request, model_info: AccountEntityNew, db: Session = Depends(get_db)) -> Response:
    try:
        # Find user in database
        acc = AccountAuthService.query_acc_by_acc_name(db=db, account_name=model_info.account_name)
        if not acc:
            return RetUtil.response_error(message="账号不存在")
        acc_id = query2dict(acc, Usr_Model)["account_id"]
        acc_pw = query2dict(acc, Usr_Model)["password"]
        enpassword = md5(model_info.password)
        if acc_pw != enpassword:
            return RetUtil.response_error(message="密码错误")

        #   Verify Account Token
        token = await AccountAuthService.token_cache(request=request, account_id=acc_id, db=db)
        data = {"account_id": acc_id, "accessToken": token}

        return RetUtil.response_ok(data=data)

    except Exception as e:
        logger.error("服务器错误", exc_info=True)
        raise HTTPException(status_code=400, detail="服务器错误")


@api_router.post("/login", summary="账号登录", response_model=AccountEntityNew)
async def login(request: Request, model_info: AccountEntityNew, db: Session = Depends(get_db)) -> Response:
    try:
        # Find user in database
        acc = AccountAuthService.query_acc_by_acc_name(db=db, account_name=model_info.account_name)
        if not acc:
            return RetUtil.response_error(message="账号不存在")
        acc_id = query2dict(acc, Usr_Model)["account_id"]
        acc_pw = query2dict(acc, Usr_Model)["password"]
        acc_type = query2dict(acc, Usr_Model)["attribute"]
        usr_name = query2dict(acc, Usr_Model)["usr_name"]
        decryptpassword = sm2decrypt(model_info.password)
        enpassword = md5(decryptpassword)
        if acc_pw != enpassword:
            return RetUtil.response_error(message="密码错误")
        #   Verify Account Token
        teams = UsrAuthService.usr_team(db=db, auth=UsrEntity(account_id=acc_id))
        permissions = UsrAuthService.usr_res_by_id(db=db, auth=UsrEntity(account_id=acc_id))
        data = {
            "avatar": "",
            "nickname": usr_name,
            "account_id": acc_id,
            "attribute": acc_type,
            "permissions": permissions,
            "teams": teams
        }
        token = await AccountAuthService.token_cache(request=request, account_id=acc_id ,db=db, usr_info=data)
        data["accessToken"]=token

        return RetUtil.response_ok(data=data)

    except Exception as e:
        logger.error("服务器错误", exc_info=True)
        raise HTTPException(status_code=400, detail="服务器错误")


@api_router.post("/u_login", summary="用户登录（明文密码）")
async def u_login(request: Request, model_info: ULoginEntity, db: Session = Depends(get_db)) -> Response:
    try:
        # Find user in database
        acc = AccountAuthService.query_acc_by_acc_name(db=db, account_name=model_info.username)
        if not acc:
            return RetUtil.response_error(message="账号不存在")
        acc_id = query2dict(acc, Usr_Model)["account_id"]
        acc_pw = query2dict(acc, Usr_Model)["password"]

        # 使用明文密码直接进行MD5加密比较
        enpassword = md5(model_info.password)
        if acc_pw != enpassword:
            return RetUtil.response_error(message="密码错误")

        # Verify Account Token
        token = await AccountAuthService.token_cache(request=request, account_id=acc_id, db=db)

        # 只返回token字段
        data = {"token": token["value"]}

        return RetUtil.response_ok(data=data)

    except Exception as e:
        logger.error("服务器错误", exc_info=True)
        raise HTTPException(status_code=400, detail="服务器错误")


