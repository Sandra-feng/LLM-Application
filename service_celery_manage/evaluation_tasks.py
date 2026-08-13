import asyncio
import os
import time
from typing import Any, Optional
from pathlib import Path
from pymilvus import utility
import numpy as np
import pandas as pd
from loguru import logger

from base_utils.excel_util import ExcelUtil
from base_utils.mongodb_util import MongodbUtil
from base_configs.mongodb_config import CollectionConfig
from base_utils.embedding_util import EmbeddingUtil
from base_utils.minio_util import MinIoUtil
from base_utils.mysql_util import SessionLocal
from service_knowledge_manage.entity.knowledge_hub_entity import KnowledgeRetrivalInfo
from .celery_app import celery_app
from sqlalchemy.orm import Session
from celery import Task


@celery_app.task(name="kb_evaluation_task")
def kb_evaluation_task(
        file_urls: list[str],
        knowledge_id: str,
        file_id: str,
        evaluation_id: str,
        search_type: str,
        is_rerank: bool,
        rerank_id: str,
        rerank_model: str,
        recall_num: int,
        rerank_num: int,
        score: float,
        needEnhanceRounds: bool,
        enhance_rounds: int,
        semantics_weights: float,
        keywords_weights: float,
        similarity_threshold: float,
        task_name: str,
):
    """
    知识库评估 Celery 任务
    状态（status）：
    - 1: 排队中（已在接口中设置）
    - 2: 评测中（正式执行）
    - 3: 已完成
    - 4: 失败
    """
    db = None
    local_path = None
    try:
        # 创建数据库会话
        db = SessionLocal()

        # Lazy import to avoid circular dependency
        from service_knowledge_manage.service.knowledge_evaluation import Knowledge_Evaluation_service
        from service_knowledge_manage.entity.knowledge_entity import KnowledgeEvaluationRequest, RetrivalInfo, \
            KNOWLEDGE_EVALUATION, KnowledgeEvaluationSetting
        from fastapi import UploadFile

        # 更新状态为 2（评测中）
        db.query(KnowledgeEvaluationSetting).filter(
            KnowledgeEvaluationSetting.evaluation_id == evaluation_id
        ).update({
            KnowledgeEvaluationSetting.status: 2,
            KnowledgeEvaluationSetting.message: None
        })
        db.commit()

        logger.info(f"开始执行知识库评估任务，file_id: {file_id}, file_urls: {file_urls}")

        # 处理每个文件（通常只有一个）
        for file_url in file_urls:
            # 下载文件到本地
            upload_path = Path(__file__).parents[2] / "upload"
            upload_path.mkdir(parents=True, exist_ok=True)
            file_name = file_url.split("/")[-1]
            local_path = f"{upload_path}/{file_id}_{file_name}"

            # 下载文件
            bucket_name = "tiance-base"
            MinIoUtil.download_file(bucket_name, file_url, local_path)

            if not os.path.exists(local_path):
                raise Exception(f"文件下载失败: {file_url}")

            # 构建 RetrivalInfo
            retrival_params = RetrivalInfo(
                id=knowledge_id,
                search_type=search_type,
                recall_num=recall_num,
                rerank_id=rerank_id if is_rerank else "",
                rerank_model=rerank_model if is_rerank else "",
                rerank_num=rerank_num if is_rerank else 0,
                score=score,
                is_rerank=is_rerank,
                enhance_rounds=enhance_rounds if needEnhanceRounds else 0,
                semantics_weights=semantics_weights,
                keywords_weights=keywords_weights,
            )

            # 构建 KnowledgeEvaluationRequest
            eval_request = KnowledgeEvaluationRequest(
                file_url=file_url,
                retrival_params=retrival_params,
                knowledge_id=knowledge_id,
                similarity_threshold=similarity_threshold,
                task_name=task_name,
                task_id=evaluation_id,
                remote_path=file_url,
                evaluation_id=evaluation_id
            )

            # 调用 process_evaluation
            evaluation_service = Knowledge_Evaluation_service()
            
            # 处理异步函数调用，避免 "Event loop is closed" 错误
            # 注意：不能使用 asyncio.run()，因为它会在完成后关闭事件循环
            # 而 Milvus 的 gRPC 客户端可能仍然持有对事件循环的引用
            # 应该使用手动管理的事件循环，确保在同一个循环中创建和使用 Milvus 客户端
            
            # 导入全局的 knowledge_retrieval_service，以便重置其 Milvus 连接
            from service_knowledge_manage.service.knowledge_retrieval_service import knowledge_retrieval_service
            
            # 创建一个包装函数，确保在事件循环中重置 Milvus 连接
            async def run_evaluation_with_reset():
                # 在事件循环中重置 Milvus 连接，确保在新的事件循环中重新创建
                knowledge_retrieval_service.milvus_util = None
                return await evaluation_service.process_evaluation(
                    file_path=local_path,
                    file_id=file_id,
                    request=eval_request,
                    db=db
                )
            
            loop = None
            try:
                # 尝试获取当前事件循环
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_closed():
                        # 如果已关闭，创建一个新的事件循环
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                except RuntimeError:
                    # 如果没有事件循环，创建一个新的
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                result = loop.run_until_complete(run_evaluation_with_reset())
            except RuntimeError as e:
                # 如果仍然失败，尝试创建并使用新的事件循环
                error_msg = str(e).lower()
                if "event loop is closed" in error_msg or "no current event loop" in error_msg or "attached to a different loop" in error_msg:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(run_evaluation_with_reset())
                else:
                    raise
            finally:
                # 确保所有待处理的任务都完成
                if loop and not loop.is_closed():
                    try:
                        # 等待所有待处理的任务完成（Python 3.10 需要传入 loop 参数）
                        pending = asyncio.all_tasks(loop)
                        if pending:
                            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    except Exception as e:
                        logger.warning(f"清理待处理任务时出错: {e}")
                        pass
            # 更新状态为 3（已完成）
            if result.get("success", False):
                db.query(KnowledgeEvaluationSetting).filter(
                    KnowledgeEvaluationSetting.evaluation_id == evaluation_id
                ).update({
                    KnowledgeEvaluationSetting.status: 3
                })
                db.commit()
                logger.info(f"知识库评估任务完成，file_id: {file_id}")
            else:
                # 评估失败
                db.query(KnowledgeEvaluationSetting).filter(
                    KnowledgeEvaluationSetting.evaluation_id == evaluation_id
                ).update({
                    KnowledgeEvaluationSetting.status: 4,
                    KnowledgeEvaluationSetting.message: result.get("message", "")
                })
                db.commit()
                logger.error(f"知识库评估任务失败，file_id: {file_id}, 错误: {result.get('message', '')}")

    except Exception as e:
        logger.exception(f"知识库评测任务失败: {e}")
        # 更新状态为 4（失败）
        if db:
            try:
                db.query(KnowledgeEvaluationSetting).filter(
                    KnowledgeEvaluationSetting.evaluation_id == evaluation_id
                ).update({
                    KnowledgeEvaluationSetting.status: 4,
                    KnowledgeEvaluationSetting.message: str(e)
                })
                db.commit()
            except Exception as db_error:
                logger.error(f"更新失败状态时出错: {db_error}")
    finally:
        # 清理资源
        if db:
            db.close()
        if local_path and os.path.exists(local_path):
            try:
                os.remove(local_path)
            except Exception as e:
                logger.warning(f"清理临时文件失败: {e}")

