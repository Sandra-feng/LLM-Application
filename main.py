import warnings

# 抑制 LangChain 1.0 版本重构导致的废弃警告
warnings.filterwarnings("ignore", message=".*AgentStatePydantic has been moved.*", category=DeprecationWarning)

import mimetypes
import os

import uvicorn
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from base_configs.api_config import ApiConfig
from base_configs.log_config import setup_logging

# 初始化日志（统一配置）
from observability.request_context import RequestContextMiddleware
from service_synonym_manage.api import synonym_manage_api

# 环境变量应该在所有模块之前加载
base_dir = os.path.abspath(os.path.dirname(__file__))
dotenv_path = os.path.join(base_dir, ".local.env")
if not os.path.exists(dotenv_path):
    dotenv_path = os.path.join(base_dir, ".production.env")
load_dotenv(dotenv_path=dotenv_path)

setup_logging()

from contextlib import asynccontextmanager, contextmanager

import pymysql

from base_utils.minio_util import MinIoUtil
from base_utils.mongodb_util import MongodbUtil
from data_access.implementations.minio_repository import MinioRepository
from data_access.implementations.mongo_repository import MongoRepository

pymysql.install_as_MySQLdb()


from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import sessionmaker
from starlette.middleware.base import BaseHTTPMiddleware

from auth_center.api import auth_center_api
from auth_center.service.auth_service import AccountAuthService
from base_utils.mysql_util import MySQLUtil
from base_utils.redis_util import RedisUtil
from service_agent_manage.api import agent_manage_api
from service_config_manage.api import config_manage_api
from service_knowledge_manage.api import knowledge_manage_api
from service_mcp_manage.api import mcp_manage_api
from service_model_manage.api import model_manage_api
from service_permission_auth.api import permission_auth_api
from service_permission_manage.api import permission_manage_api
from service_prompt_manage.api import prompt_manage_api
from service_toolset_manage.api import toolset_manage_api
from service_train_manage.api import dataset_manage_api
from service_usr_manage.api import usr_manage_api
from service_workflow_manage.api import workflow_manage_api

mimetypes.add_type("application/javascript", ".js")


MOUNT_STATIC_FILES = os.getenv("MOUNT_STATIC_FILES")
logger.info(f"MOUNT_STATIC_FILES: {MOUNT_STATIC_FILES}")


# ---------- 合并后的 lifespan ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    # 初始化所有客户端实例
    mongo_client = MongoRepository()
    mongo_client.connect()
    minio_client = MinioRepository()
    minio_client.connect()

    # 初始化Facades
    MongodbUtil.initialize(mongo_client)
    MinIoUtil.initialize(minio_client)

    engine = MySQLUtil.creat_engine()
    AsyncSessionLocal = async_sessionmaker(
        autocommit=False, autoflush=False, bind=MySQLUtil.creat_async_engine(), class_=AsyncSession
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    RedisPool = await RedisUtil.get_redis_pool()

    app.state.redis_pool = RedisPool
    app.state.engine = engine
    app.state.SessionLocal = SessionLocal
    app.state.AsyncSessionLocal = AsyncSessionLocal
    # 将客户端实例也存储在 app.state 中，添加以作备用
    app.state.mongo_client = mongo_client
    app.state.minio_client = minio_client

    db = SessionLocal()
    try:
        await AccountAuthService.config_cache(redis=RedisPool, db=db, keyword="API_Whitelist1")
        await AccountAuthService.config_cache(redis=RedisPool, db=db, keyword="API_OutAuth1")
        await AccountAuthService.config_cache(redis=RedisPool, db=db, keyword="token_expire")
    finally:
        db.close()

    logger.info("LLM平台服务启动")
    yield
    # Shutdown logic
    if hasattr(app.state.mongo_client, "close"):
        app.state.mongo_client.close()

    app.state.redis_pool.close()
    await app.state.redis_pool.wait_closed()
    if app.state.engine:
        app.state.engine.dispose()
    logger.info("服务已关闭")


# ---------- FastAPI 实例 ----------
app = FastAPI(
    title="LLM平台服务接口",
    description="提供配置管理，模型管理，知识库管理，工具管理，智能体管理服务",
    version=ApiConfig.MODEL_SERVICE_VERSION,
    lifespan=lifespan,  # ← 关键：用合并后的 lifespan
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # 根据需要构造 JSON 响应
    return JSONResponse(
        content={"code": exc.status_code, "status": False, "message": exc.detail}, status_code=exc.status_code
    )


@contextmanager
def get_db(request: Request):
    db = request.app.state.SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ModifyPathMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next,
    ):
        try:
            # 验证接口
            redis = request.app.state.redis_pool
            with get_db(request) as db:
                await AccountAuthService.token_verify(request, redis=redis, db=db)
            response = await call_next(request)
            return response
        except HTTPException as e:
            return JSONResponse(
                status_code=e.status_code, content={"code": e.status_code, "status": False, "message": e.detail}
            )


# 请求上下文中间件放在最前，确保后续日志具备 request_id 等上下文
app.add_middleware(RequestContextMiddleware)
app.add_middleware(ModifyPathMiddleware)

# 配置跨源资源共享（CORS）中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源
    allow_credentials=True,  # 允许凭据
    allow_methods=["*"],  # 允许所有 HTTP 方法
    allow_headers=["*"],  # 允许所有请求头
)
app.include_router(config_manage_api.api_router, prefix=ApiConfig.ROOT_ROUTE)
app.include_router(model_manage_api.api_router, prefix=ApiConfig.ROOT_ROUTE)
app.include_router(auth_center_api.api_router, prefix=ApiConfig.ROOT_ROUTE)
app.include_router(knowledge_manage_api.api_router, prefix=ApiConfig.ROOT_ROUTE)

app.include_router(toolset_manage_api.api_router, prefix=ApiConfig.ROOT_ROUTE)
app.include_router(dataset_manage_api.api_router, prefix=ApiConfig.ROOT_ROUTE)
app.include_router(agent_manage_api.api_router, prefix=ApiConfig.ROOT_ROUTE)
app.include_router(workflow_manage_api.api_router, prefix=ApiConfig.ROOT_ROUTE)
app.include_router(permission_manage_api.api_router, prefix=ApiConfig.ROOT_ROUTE)
app.include_router(permission_auth_api.api_router, prefix=ApiConfig.ROOT_ROUTE)
app.include_router(usr_manage_api.api_router, prefix=ApiConfig.ROOT_ROUTE)
app.include_router(prompt_manage_api.api_router, prefix=ApiConfig.ROOT_ROUTE)
app.include_router(synonym_manage_api.api_router, prefix=ApiConfig.ROOT_ROUTE)
app.include_router(mcp_manage_api.api_router, prefix=ApiConfig.ROOT_ROUTE)
# app.mount("/", StaticFiles(directory="web/dist", html=True), name="web")
if MOUNT_STATIC_FILES == "true":
    app.mount("/", StaticFiles(directory="web/dist", html=True), name="web")

if __name__ == "__main__":
    # 配置uvicorn日志，禁用默认的访问日志以避免重复
    uvicorn.run(
        "main:app",
        host=ApiConfig.SERVICE_IP,
        port=ApiConfig.SERVICE_PORT,
        reload=True,
        log_config=None,
        access_log=False,  # 禁用uvicorn的访问日志，由Loguru统一处理
    )
    # uvicorn.run("main:app", host=ApiConfig.SERVICE_IP, port=ApiConfig.SERVICE_PORT, workers=3,reload=False)

