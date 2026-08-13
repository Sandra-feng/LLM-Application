import uvicorn

# 初始化日志（统一配置）
from observability.logging_config import get_logger, setup_logging_from_env
from observability.request_context import RequestContextMiddleware
from service_app_getway.base_configs.api_config import ApiConfig
from service_app_getway.base_utils.log_util import LogUtil

_active_log_cfg = setup_logging_from_env()
logger = get_logger("tiance-app-gateway")

# 兼容旧工具初始化（不再新增 handler）
LogUtil.init(process_name="tiance-app-gateway")

import pymysql

pymysql.install_as_MySQLdb()
from service_app_getway.base_utils.mysql_util import MySQLUtil

MySQLUtil.creat_engine()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from service_app_getway.api import app_getway

# 创建一个FastAPI实例
app = FastAPI(
    title="天策基座平台网关服务接口",
    description="网关服务",
    version=ApiConfig.MODEL_SERVICE_VERSION,
)

# 请求上下文中间件
app.add_middleware(RequestContextMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源
    allow_credentials=True,  # 允许凭据
    allow_methods=["*"],  # 允许所有 HTTP 方法
    allow_headers=["*"],  # 允许所有请求头
)
app.include_router(app_getway.api_router, prefix=ApiConfig.ROOT_ROUTE)
logger.info("天策基座平台网关服务启动")

if __name__ == "__main__":
    uvicorn.run(app, host=ApiConfig.SERVICE_IP, port=8989, log_config=_active_log_cfg)
