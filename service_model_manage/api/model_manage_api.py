

from fastapi import APIRouter

from base_configs.api_config import ApiConfig
from service_model_manage.api.routes import (
    audio_route,
    embedding_model_route,
    launch_route,
    llm_chat_completion_route,
    markdown_to_doc_route,
    model_family_route,
    model_supervise_route,
    rerank_model_route,
    text_to_image_route,
)

api_router = APIRouter()

api_router.include_router(launch_route.router, prefix=ApiConfig.MODEL_MANAGE_ROUTE, tags=["模型启动"])
api_router.include_router(
    model_family_route.router,
    prefix=ApiConfig.MODEL_MANAGE_ROUTE,
    tags=["模型家族管理"],
)
api_router.include_router(
    model_supervise_route.router,
    prefix=ApiConfig.MODEL_MANAGE_ROUTE,
    tags=["模型家族管理"],
)
api_router.include_router(
    llm_chat_completion_route.router,
    prefix=ApiConfig.MODEL_MANAGE_ROUTE,
    tags=["LLM模型对话服务"],
)
api_router.include_router(
    embedding_model_route.router,
    prefix=ApiConfig.MODEL_MANAGE_ROUTE,
    tags=["embedding模型服务"],
)
api_router.include_router(
    rerank_model_route.router,
    prefix=ApiConfig.MODEL_MANAGE_ROUTE,
    tags=["rerank模型服务"],
)
api_router.include_router(
    audio_route.router,
    prefix=ApiConfig.MODEL_MANAGE_ROUTE,
    tags=["语音模型服务"],
)
api_router.include_router(text_to_image_route.router, prefix=ApiConfig.MODEL_MANAGE_ROUTE, tags=["文生图模型服务"])
api_router.include_router(markdown_to_doc_route.router, prefix=ApiConfig.MODEL_MANAGE_ROUTE, tags=["文档pdf生成服务"])
