from base_configs.minio_config import MinioConfig
import uuid
from service_knowledge_manage.entity.knowledge_entity import KNOWLEDGE_EVALUATION
import datetime
import os
import aiofiles
from fastapi import FastAPI, File, UploadFile
from base_utils.minio_util import MinIoUtil
"""
@File         :knowledge_hub_route.py
@Description  :
@Author       :QiangQu
@Date         :2024/09/04 09:53:32
"""
from fastapi.concurrency import run_in_threadpool
from base_utils.minio_util import MinIoUtil
from service_knowledge_manage.service.knowledge_evaluation import Knowledge_Evaluation_service
#!/usr/bin/env python
from service_synonym_manage.api.routes.synonym_group_route import get_db
from fastapi.responses import JSONResponse
from requests import Session
from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import Response
from loguru import logger
from base_utils.ret_util import RetUtil
from service_knowledge_manage.entity.knowledge_hub_entity import (
    KnowledgeRetrivalInfo,
    KnowledgeRetrivalResponse,
)
from service_knowledge_manage.service.knowledge_retrieval_service import knowledge_retrieval_service
from service_knowledge_manage.entity.knowledge_entity import (
    KnowledgeEvaluationRequest,
    EvaluationQuestion,
    EvaluationAnswer,
    EvaluationResult,
    KnowledgeEvaluationSetting,
)
from celery.result import AsyncResult
from service_celery_manage.celery_app import celery_app
from base_utils.mongodb_util import MongodbUtil
from base_configs.mongodb_config import CollectionConfig
from bson import ObjectId

import asyncio
import json
import os
import re
import subprocess
from datetime import datetime
from typing import Optional

import aiofiles
import openpyxl
import pandas as pd
from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pymilvus.exceptions import MilvusException
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from base_configs.mongodb_config import CollectionConfig
from base_utils.mongodb_util import MongodbUtil
from base_utils.mysql_util import SessionLocal
from base_utils.ret_util import RetUtil
from service_knowledge_manage.entity.knowledge_hub_entity import KnowledgeRetrivalInfo
from service_knowledge_manage.service.knowledge_file_service import (
    Knowledge_File_service,
)
from service_knowledge_manage.service.parse_service import FileParseService
from service_knowledge_manage.service.knowledge_service import KnowledgeService
from service_usr_manage.service.snow_util import generate_unique_id
from pathlib import Path
router = APIRouter()


@router.post(
    "/knwolege_retrieval",
    summary="知识库检索",
    response_model=KnowledgeRetrivalResponse,
)
async def knwolege_retrieval(params: KnowledgeRetrivalInfo) -> Response:
    """
    知识库检索接口

    使用统一的知识检索服务进行知识库检索，支持多种检索模式：
    - 语义检索（默认）
    - BM25检索
    - 混合检索
    - 支持重排序和增强检索
    """
    try:
        # 调用统一的知识检索服务
        result = await knowledge_retrieval_service.advanced_knowledge_retrieval(params)
        return RetUtil.response_ok(data=result.model_dump())


    except Exception as e:
        logger.exception(f"知识库检索失败: {e}")
        return RetUtil.response_error(message=f"知识库检索失败: {e}")


@router.post("/kb_query_retrieval", summary="查询知识库检索配置信息")
async def kb_query_retrieval(
    kb_id: str = Body(..., description="知识库ID", embed=True)
) -> Response:
    """
    查询知识库检索配置信息
    返回知识库的描述信息和检索相关配置参数
    """

    try:
        # 检查知识库是否存在
        condition = {"_id": ObjectId(kb_id)}
        is_exist = await KnowledgeService.is_knowledge_exist(condition)
        if not is_exist:
            return RetUtil.response_error(message="知识库不存在")

        # 获取知识库描述
        description = await KnowledgeService.get_kb_describe(kb_id)

        # 从 MongoDB 查询知识库信息
        kb_result = MongodbUtil.query_docs_by_condition(
            collection_name=CollectionConfig.KB_COLLECTION,
            search_condition={"_id": ObjectId(kb_id)},
        )

        # 获取第一条记录
        kb = next(iter(kb_result), None)
        if not kb:
            return RetUtil.response_error(message="知识库信息不存在")

        # 提取检索相关参数
        prompt = kb.get("prompt", "")
        retrieval_count = kb.get("retrieval_count", 10)
        rerank_model = kb.get("rerank_model", "")
        top_k = kb.get("top_k", 5)
        score = kb.get("score", 0.5)
        rerank_id = kb.get("rerank_id", "")
        enhance_rounds = kb.get("enhance_rounds", 0)
        max_tokens = kb.get("max_tokens", None)
        search_type = kb.get("search_type", "semantic")
        fusion_weights = kb.get("fusion_weights", [0.7, 0.3])
        is_rerank = kb.get("is_rerank", False)

        # 构建返回信息
        describe_info = {
            "description": description,
            "id": kb_id,
            "prompt": prompt,
            "retrieval_count": retrieval_count,
            "rerank_model": rerank_model,
            "top_k": top_k,
            "score": score,
            "rerank_id": rerank_id,
            "enhance_rounds": enhance_rounds,
            "max_tokens": max_tokens,
            "search_type": search_type,
            "fusion_weights": fusion_weights,
            "is_rerank": is_rerank,
        }
        return RetUtil.response_ok(describe_info)

    except Exception as e:
        logger.exception(f"查询知识库检索配置信息失败: {e}")
        return RetUtil.response_error(message=f"查询知识库检索配置信息失败: {e}")


# 评测处理接口
@router.post("/KnowledgeEvaluate", summary="知识库评测")
async def KnowledgeEvaluate(
    request: KnowledgeEvaluationRequest,  # 请求体参数
    file: UploadFile = File(...),  # 文件上传参数
    db: Session = Depends(get_db)  # 依赖注入数据库会话
) -> JSONResponse:
    local_path = None
    try:
        # 获取文件名
        file_name = file.filename
        if not file_name:
            return RetUtil.response_error(message="文件名不能为空")

        # 保存文件到本地临时目录
        upload_path = Path(__file__).parents[2] / "upload"
        upload_path.mkdir(parents=True, exist_ok=True)
        local_path = f"{upload_path}/{file_name}"

        # 异步写入文件内容
        async with aiofiles.open(local_path, "wb") as temp_file:
            content = await file.read()
            await temp_file.write(content)

        # 生成远程路径：使用时间戳确保唯一性
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        remote_path = f"evaluation/{request.knowledge_id}/{timestamp}-{file_name}"

        # 上传文件到 MinIO 正式桶
        bucket_name = MinioConfig.BUCKET_NAME  # tiance-base
        await run_in_threadpool(MinIoUtil.upload_file, bucket_name, remote_path, local_path)

        # 生成 file_id
        file_id = uuid.uuid4().hex

        # 获取文件大小
        file_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0

        # 保存到 KNOWLEDGE_EVALUATION 表（不再包含状态字段）
        task = KNOWLEDGE_EVALUATION(
            file_id=file_id,
            file_name=file_name,
            file_url=remote_path,
            kb_id=request.knowledge_id,
            size=file_size,
            create_time=datetime.now(),
        )
        db.add(task)
        db.commit()
        # 初始化评测设置记录为进行中（2）
        await Knowledge_Evaluation_service.save_evaluation_setting(
            db=db,
            request=request,
            file_id=file_id,
            status=2
        )
        # 处理评测,保存评测结果
        result = await Knowledge_Evaluation_service.process_evaluation(local_path, file_id, request, db)
        # 返回评测结果
        return {"message": "Evaluation completed", "result": result}
    except Exception as e:
        logger.exception(f"知识库评测失败: {e}")
        return RetUtil.response_error(message=f"知识库评测失败: {e}")
    finally:
        if os.path.exists(local_path):
            os.remove(local_path)


@router.post("/kb_evaluation", summary="知识库评估")
async def kb_evaluation(
    kb_id: str = Body(..., description="知识库ID"),
    file_id: str = Body(..., description="文件ID（来自evaluation_file_upload的file_id）"),
    search_type: str = Body(..., description="检索类型"),
    is_rerank: bool = Body(False, description="是否重排"),
    rerank_id: str = Body("", description="重排模型ID"),
    rerank_model: str = Body("", description="重排模型名称"),
    recall_num: int = Body(10, description="召回数量"),
    rerank_num: int = Body(3, description="重排数量"),
    score: float = Body(0.1, description="重排分数阈值"),
    needEnhanceRounds: bool = Body(False, description="是否需要增强轮数"),
    enhance_rounds: int = Body(0, description="增强轮数"),
    semantics_weights: float = Body(0.7, description="语义检索权重"),
    keywords_weights: float = Body(0.3, description="关键词检索权重"),
    similarity_threshold: float = Body(0.5, description="任务阈值"),
    task_name: str = Body("", description="任务名称"),
    db: Session = Depends(get_db)
) -> Response:
    """
    知识库评估主入口
    将评估任务提交到celery异步执行，并更新进度状态
    """
    try:
        from service_celery_manage.evaluation_tasks import kb_evaluation_task
        
        # 生成评估ID（如果未提供）

        evaluation_id = uuid.uuid4().hex

        # 验证 file_id 是否存在
        task = db.query(KNOWLEDGE_EVALUATION).filter(KNOWLEDGE_EVALUATION.file_id == file_id).first()
        if not task:
            return RetUtil.response_error(message=f"文件ID {file_id} 不存在")
        file_url=task.file_url
        # 检查同一文件下任务名称是否重复
        if task_name:
            existing_setting = (
                db.query(KnowledgeEvaluationSetting)
                .filter(
                    KnowledgeEvaluationSetting.file_id == file_id,
                    KnowledgeEvaluationSetting.evaluation_name == task_name,
                )
                .first()
            )
            if existing_setting:
                return RetUtil.response_error(message=f"任务名称重复!")

        # 创建/保存评测设置，状态为 1（排队中）
        from service_knowledge_manage.entity.knowledge_entity import KnowledgeEvaluationRequest, RetrivalInfo
        if rerank_id != "":
            rerank_model_data = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                    doc_id=ObjectId(rerank_id),
                )
            if rerank_model_data:
                rerank_model = rerank_model_data.get("model_uid", "") or rerank_model
        retrival = RetrivalInfo(
            id=kb_id,
            search_type=search_type,
            recall_num=recall_num,
            rerank_id=rerank_id if is_rerank else "",
            rerank_model=rerank_model if is_rerank else "",
            is_rerank=is_rerank,
            rerank_num=rerank_num if is_rerank else 0,
            score=score,
            enhance_rounds=enhance_rounds if needEnhanceRounds else 0,
            semantics_weights=semantics_weights,
            keywords_weights=keywords_weights,
        )
        req = KnowledgeEvaluationRequest(
            file_url=file_url,
            retrival_params=retrival,
            knowledge_id=kb_id,
            similarity_threshold=similarity_threshold,
            task_name=task_name,
            task_id=evaluation_id,
            remote_path=file_url,
            evaluation_id=evaluation_id
        )
        await Knowledge_Evaluation_service().save_evaluation_setting(db=db, request=req, file_id=file_id, status=1)
        
        logger.info(f"开始知识库评估，知识库ID: {kb_id}, 文件ID: {file_id}, 文件URL: {file_url}")
        
        # 将单个文件URL转换为列表，传递给celery任务
        file_urls = [file_url]
        
        # 提交到 Celery 异步任务（使用 class-based 任務）
        task_id = f"{evaluation_id}:evaluation"
        kb_evaluation_task.apply_async(
            args=(
                file_urls,
                kb_id,
                file_id,
                evaluation_id,
                search_type,
                is_rerank,
                rerank_id,
                rerank_model,
                recall_num,
                rerank_num,
                score,
                needEnhanceRounds,
                enhance_rounds,
                semantics_weights,
                keywords_weights,
                similarity_threshold,
                task_name,
            ),
            task_id=task_id,
            queue="kb_evaluation",
        )
        
        return RetUtil.response_ok(data={
            "file_id": file_id,
            "status": 1
        })

    except Exception as e:
        logger.exception(f"知识库评估任务提交失败: {e}")
        if db:
            db.rollback()
        return RetUtil.response_error(message=f"知识库评估任务提交失败: {e}")



@router.post("/evaluation_file_upload", summary="知识库评估文件上传")
async def evaluation_file_upload(
    kb_id: str = Form(..., description="知识库ID"),
    file_obj: UploadFile = File(..., description="上传的文件"),
    db: Session = Depends(get_db)
):
    """
    知识库评估文件上传接口
    将文件保存到minio正式桶，并保存相关信息到KNOWLEDGE_EVALUATION表
    """
    local_path = None
    try:
        from base_configs.minio_config import MinioConfig
        
        # 获取文件名
        file_name = file_obj.filename
        if not file_name:
            return RetUtil.response_error(message="文件名不能为空")
        
        # 保存文件到本地临时目录
        upload_path = Path(__file__).parents[2] / "upload"
        upload_path.mkdir(parents=True, exist_ok=True)
        local_path = f"{upload_path}/{file_name}"
        
        # 异步写入文件内容
        async with aiofiles.open(local_path, "wb") as temp_file:
            content = await file_obj.read()
            await temp_file.write(content)
        
        # 验证文件格式和内容
        verify_response = await evaluation_file_verify(file_path=local_path)
        
        try:
            if verify_response.get('status') is False:
                return RetUtil.response_error(code=400, message=verify_response.get('message'), data=verify_response.get('data'))
        except Exception as e:
            logger.error(f"解析验证响应失败: {e}")
            return JSONResponse({"code":400, "status": False, "message": "文件验证失败", "data": {"is_valid": False}}, status_code=400)
        
        # 生成远程路径：使用时间戳确保唯一性
        file_id = uuid.uuid4().hex
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        remote_path = f"evaluation/{kb_id}/{file_id}_{timestamp}"
        
        # 上传文件到 MinIO 正式桶
        bucket_name = MinioConfig.BUCKET_NAME  # tiance-base
        await run_in_threadpool(MinIoUtil.upload_file, bucket_name, remote_path, local_path)
        
        # 生成 file_id

        # 获取文件大小
        file_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0
        
        # 保存到 KNOWLEDGE_EVALUATION 表（不再包含状态字段）
        task = KNOWLEDGE_EVALUATION(
            file_id=file_id,
            file_name=file_name,
            file_url=remote_path,
            kb_id=kb_id,
            size=file_size,
            create_time=datetime.now(),
        )
        db.add(task)
        db.commit()

        #读取文件内容，保存问题答案对到 EvaluationQuestion 表
        df = pd.read_excel(local_path)
        # 假设问题和标准答案在列 '评测问题' 和 '标准答案' 中
        questions = df['评测问题'].tolist()
        standard_answers = df['标准答案'].tolist()
        i=0
        for question, standard_answer in zip(questions, standard_answers):
            i = i+1
            question_task = EvaluationQuestion(
                file_id=file_id,
                question_index=i,
                question_id=uuid.uuid4().hex,
                question=question.strip(),
                create_time=datetime.now(),
                standard_answer=standard_answer.strip()
                    )
            db.add(question_task)
        db.commit()
        
        logger.info(f"评测文件已上传: file_id={file_id}, file_name={file_name}, remote_path={remote_path}")
        
        return RetUtil.response_ok(data={
            "file_id": file_id,
            "file_name": file_name,
            "file_url": remote_path,
            "message": "文件上传成功"
        })
        
    except Exception as e:
        logger.exception(f"知识库评估文件上传失败: {e}")
        if db:
            db.rollback()
        return RetUtil.response_error(message=f"知识库评估文件上传失败: {e}")
    finally:
        # 清理本地临时文件
        if local_path and os.path.exists(local_path):
            try:
                os.remove(local_path)
            except Exception as e:
                logger.warning(f"清理临时文件失败: {e}")


@router.post("/evaluation_stop", summary="中止评测任务")
async def evaluation_stop(
        request: Request,  # 完全保留原request参数，不改为Body
        db: Session = Depends(get_db)
) -> Response:
    """
    中止评测任务
    取消celery任务执行，更新进度状态，但不删除数据
    """
    try:
        data = await request.json()
        file_id = data.get("file_id")
        Knowledge_Evaluation_service.abort_evaluation_task(db=db, file_id=file_id)
        return RetUtil.response_ok(data={
            "message": "评测任务已中止",
            "file_id": file_id
        })

    except Exception as e:
        logger.exception(f"中止评测任务失败: {e}")
        if db:
            db.rollback()
        return RetUtil.response_error(message=f"中止评测任务失败: {e}")


@router.delete("/evaluation_file_delete", summary="删除评测文件")
async def evaluation_file_delete(
    file_id: str = Body(..., description="文件ID", embed=True),
    db: Session = Depends(get_db)
) -> Response:
    """
    删除评测文件相关的所有数据
    能够保证调用时celery任务一定已经执行完成
    使用硬删除
    """
    try:
        # 查询任务是否存在
        task = db.query(KNOWLEDGE_EVALUATION).filter(KNOWLEDGE_EVALUATION.file_id == file_id).first()
        if not task:
            return RetUtil.response_error(message=f"文件ID {file_id} 不存在")
        
        # 查询该 file_id 对应的所有 evaluation_id（通过 KnowledgeEvaluationSetting）
        evaluation_settings = db.query(KnowledgeEvaluationSetting).filter(
            KnowledgeEvaluationSetting.file_id == file_id
        ).all()
        evaluation_ids = [setting.evaluation_id for setting in evaluation_settings]
        
        # 删除相关的评测数据（硬删除）
        # 1. 删除 EvaluationQuestion（通过 file_id）
        db.query(EvaluationQuestion).filter(EvaluationQuestion.file_id == file_id).delete()
        
        # 2. 删除 EvaluationAnswer（通过 evaluation_id）
        if evaluation_ids:
            db.query(EvaluationAnswer).filter(
                EvaluationAnswer.evaluation_id.in_(evaluation_ids)
            ).delete()
        
        # 3. 删除 EvaluationResult（通过 evaluation_id）
        if evaluation_ids:
            db.query(EvaluationResult).filter(
                EvaluationResult.evaluation_id.in_(evaluation_ids)
            ).delete()
        
        # 4. 删除 KnowledgeEvaluationSetting（通过 file_id）
        db.query(KnowledgeEvaluationSetting).filter(
            KnowledgeEvaluationSetting.file_id == file_id
        ).delete()
        
        # 5. 删除 KNOWLEDGE_EVALUATION 记录
        db.delete(task)
        
        db.commit()
        
        # 删除 MinIO 中的文件
        if task.file_url:
            try:
                from base_configs.minio_config import MinioConfig
                bucket_name = MinioConfig.BUCKET_NAME
                # 使用完整的remote_path删除文件
                remote_path = task.file_url
                MinIoUtil.delete_file(bucket_name=bucket_name, file_path=remote_path)
            except Exception as e:
                logger.warning(f"删除MinIO文件失败: {e}")
        
        logger.info(f"评测文件已删除: file_id={file_id}")
        
        return RetUtil.response_ok(data={
            "message": "评测文件删除成功",
            "file_id": file_id
        })
        
    except Exception as e:
        logger.exception(f"删除评测文件失败: {e}")
        if db:
            db.rollback()
        return RetUtil.response_error(message=f"删除评测文件失败: {e}")


@router.delete("/evaluation_delete", summary="删除评测结果")
async def evaluation_delete(
    evaluation_id: str = Body(..., description="评测ID", embed=True),
    db: Session = Depends(get_db)
) -> Response:
    """
    删除评测结果相关的所有数据
    通过evaluation_id删除该次评测的所有结果数据
    硬删除评测结果数据（EvaluationAnswer、EvaluationResult、KnowledgeEvaluationSetting）
    """
    try:
        # 查询评测设置是否存在
        evaluation_setting = db.query(KnowledgeEvaluationSetting).filter(
            KnowledgeEvaluationSetting.evaluation_id == evaluation_id
        ).first()
        
        if not evaluation_setting:
            return RetUtil.response_error(message=f"评测ID {evaluation_id} 不存在")
        
        # 获取关联的 file_id
        file_id = evaluation_setting.file_id
        
        # 硬删除相关的评测数据
        # 1. 删除 EvaluationAnswer（通过 evaluation_id）
        db.query(EvaluationAnswer).filter(
            EvaluationAnswer.evaluation_id == evaluation_id
        ).delete()
        
        # 2. 删除 EvaluationResult（通过 evaluation_id）
        db.query(EvaluationResult).filter(
            EvaluationResult.evaluation_id == evaluation_id
        ).delete()
        
        # 3. 删除 KnowledgeEvaluationSetting（通过 evaluation_id）
        db.query(KnowledgeEvaluationSetting).filter(
            KnowledgeEvaluationSetting.evaluation_id == evaluation_id
        ).delete()
        
        # 4. 检查是否还有其他evaluation_id关联到该file_id
        remaining_evaluations = db.query(KnowledgeEvaluationSetting).filter(
            KnowledgeEvaluationSetting.file_id == file_id
        ).count()
        
        # 如果没有其他evaluation了，可以考虑删除EvaluationQuestion
        # 但这里保留，因为question可能被其他evaluation使用
        # 如果需要删除question，可以单独处理
        
        db.commit()
        
        logger.info(f"评测结果已删除: evaluation_id={evaluation_id}, file_id={file_id}")
        
        return RetUtil.response_ok(data={
            "message": "评测结果删除成功",
            "evaluation_id": evaluation_id,
            "file_id": file_id
        })
        
    except Exception as e:
        logger.exception(f"删除评测结果失败: {e}")
        if db:
            db.rollback()
        return RetUtil.response_error(message=f"删除评测结果失败: {e}")


@router.post("/evaluation_query_page", summary="查询评测文件列表(分页)")
async def evaluation_query_page(
    file_name: Optional[str] = Body("", embed=True, description="文件名（可选，支持模糊查询）"),
    page: int = Body(..., embed=True, examples=[1], description="页码"),
    page_size: int = Body(..., embed=True, examples=[10], description="分页大小"),
    db: Session = Depends(get_db)
) -> Response:
    """
    查询评测文件列表（分页）
    支持按文件名模糊查询
    """
    try:
        # 参数验证
        if page < 1:
            return RetUtil.response_error(message="页码必须大于0")
        if page_size < 1:
            return RetUtil.response_error(message="分页大小必须大于0")
        
        # 构建查询条件
        query = db.query(KNOWLEDGE_EVALUATION)
        
        # 如果提供了文件名，进行模糊查询
        if file_name:
            query = query.filter(KNOWLEDGE_EVALUATION.file_name.like(f"%{file_name}%"))
        
        # 获取总数
        total = query.count()
        
        # 分页查询：按创建时间倒序排列
        offset = (page - 1) * page_size
        results = query.order_by(KNOWLEDGE_EVALUATION.create_time.desc()).offset(offset).limit(page_size).all()
        
        # 转换为字典列表
        result_list = []
        for item in results:
            # 获取最新一条评测状态
            latest_setting = db.query(KnowledgeEvaluationSetting).filter(
                KnowledgeEvaluationSetting.file_id == item.file_id
            ).order_by(KnowledgeEvaluationSetting.update_time.desc()).first()
            status_val = latest_setting.status if latest_setting else None
            result_list.append({
                "file_id": item.file_id,
                "file_name": item.file_name,
                "file_url": item.file_url,
                "status": status_val,
                "create_time": item.create_time.isoformat() if item.create_time else None
            })
        
        logger.info(f"查询评测文件列表成功，总数: {total}, 当前页: {page}, 每页: {page_size}")
        
        return RetUtil.response_ok({
            "total": total,
            "result": result_list
        })
        
    except Exception as e:
        logger.exception(f"查询评测文件列表失败: {e}")
        return RetUtil.response_error(message=f"查询评测文件列表失败: {e}")


@router.post("/evaluation_file_verify", summary="验证输入的评测文件格式和内容是否符合要求")
async def evaluation_file_verify(
    file_path: str = Body(..., embed=True, description="本地文件路径")
) -> Response:
    """
    验证本地Excel文件是否为.xlsx或者xls格式，且内容仅包含两列：
    - 评测问题
    - 标准答案

    并检测是否存在空值，返回详细提示。
    """
    try:
        # 基础参数校验
        if not file_path or not isinstance(file_path, str):
            return {"status":False,"message": "文件路径不能为空"}

        if not os.path.exists(file_path):
            return {"status":False,"message": f"文件不存在：{file_path}"}

        # 校验文件扩展名（支持 .xlsx 与 .xls）
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in [".xlsx", ".xls"]:
            return {"status":False,"message": "文件格式错误：仅支持.xlsx或.xls文件"}

        # 读取Excel（默认读取首个Sheet），根据扩展名选择引擎
        try:
            engine = "openpyxl" if ext == ".xlsx" else "xlrd"
            df = pd.read_excel(file_path, engine=engine)
        except Exception as e:
            return {"status":False,"message": f"Excel读取失败：{e}"}

        # 校验表头
        expected_cols = ["评测问题", "标准答案"]
        current_cols = [str(c).strip() for c in list(df.columns)]

        # 表头严格一致（且仅包含这两列）
        missing_cols = [c for c in expected_cols if c not in current_cols]
        extra_cols = [c for c in current_cols if c not in expected_cols]

        if missing_cols or extra_cols:
            msg_parts = []
            if missing_cols:
                msg_parts.append(f"表格缺少表头：{', '.join(missing_cols)}")
            if extra_cols:
                msg_parts.append(f"存在不允许的额外表头：{', '.join(extra_cols)}")
            msg = "；".join(msg_parts) if msg_parts else "表头不符合要求"
            return {"status":False,"message": f"表结构错误：{msg}。要求仅包含两列：评测问题、标准答案"}

        # 列校验：整列是否为空
        df["评测问题"] = df["评测问题"].fillna("").astype(str)
        df["标准答案"] = df["标准答案"].fillna("").astype(str)
        q_col = df["评测问题"].str.strip()
        a_col = df["标准答案"].str.strip()
        if q_col.eq("").all() or a_col.eq("").all():
            empty_cols = []
            if q_col.eq("").all():
                empty_cols.append("评测问题")
            if a_col.eq("").all():
                empty_cols.append("标准答案")
            return {"status":False,"message": f"表格有空列：{', '.join(empty_cols)}","data":{"empty_cols":empty_cols}}

        # 内容校验：检测空值/空白
        invalid_rows = []
        for idx, row in df.iterrows():
            q = row.get("评测问题", "").strip()
            a = row.get("标准答案", "").strip()
            if q == "" or a == "":
                invalid_rows.append(int(idx) + 2)  # +2：Excel的人类行号（含表头为第1行）

        if invalid_rows:
            return {"status":False,"message": f"表格内容存在空值，请检查以下行号：{invalid_rows}","data":{"invalid_rows":invalid_rows}}

        # 验证通过
        preview_rows = min(len(df), 3)
        preview = df.head(preview_rows).to_dict(orient="records") if preview_rows > 0 else []
        return {"status":True,"message": "文件格式与内容均符合要求"}
    except Exception as e:
        logger.exception(f"验证评测文件失败：{e}")
        return RetUtil.response_error(message=f"验证失败：{e}")


@router.post("/query_new_setting", summary="查询最新评测配置")
async def query_new_setting(
    file_id: str = Body(..., description="文件ID", embed=True),
    db: Session = Depends(get_db)
) -> Response:
    try:
        setting = db.query(KnowledgeEvaluationSetting).filter(
            KnowledgeEvaluationSetting.file_id == file_id
        ).order_by(KnowledgeEvaluationSetting.create_time.desc()).first()

        if not setting:
            return RetUtil.response_error(message="未找到对应文件的评测配置")

        data = {
            "evaluation_name": setting.evaluation_name,
            "similarity_threshold": setting.similarity_threshold,
            "search_type": setting.search_type,
            "recall_num": setting.recall_num,
            "is_rerank": setting.is_rerank,
            "rerank_id": setting.rerank_id,
            "rerank_model": setting.rerank_model,
            "rerank_num": setting.rerank_num,
            "score": setting.score,
            "needEnhanceRounds": setting.needEnhanceRounds,
            "enhance_rounds": setting.enhance_rounds,
            "semantics_weights": setting.semantics_weights,
            "keywords_weights": setting.keywords_weights,
        }
        return RetUtil.response_ok(data)
    except Exception as e:
        logger.exception(f"查询最新评测配置失败: {e}")
        return RetUtil.response_error(message=f"查询最新评测配置失败: {e}")
    
@router.post("/compare_tasks", summary="对比两个任务的评估指标")
async def compare_tasks(
    from_id: str = Body(..., description="起始任务ID", embed=True, alias="from"),
    to_id: str = Body(..., description="目标任务ID", embed=True, alias="to"),
    db: Session = Depends(get_db)
):
    """对比两个任务的评估指标"""
    try:
        # 检查评测结果是否存在（evaluation_result表）
        # 这里根据传入的任务ID，查询对应的评测结果记录（按更新时间取最新一条）
        from_task = db.query(EvaluationResult).\
            filter(EvaluationResult.evaluation_id == from_id).\
            order_by(EvaluationResult.update_time.desc()).first()

        to_task = db.query(EvaluationResult).\
            filter(EvaluationResult.evaluation_id == to_id).\
            order_by(EvaluationResult.update_time.desc()).first()

        if not from_task or not to_task:
            return RetUtil.response_error(message="评测结果不存在,请先进行评测")

        # 比较两个任务的评估指标
        comparison = Knowledge_Evaluation_service.compare_task_metrics(from_task, to_task)

        return RetUtil.response_ok(comparison)
    except Exception as e:
        logger.exception(f"对比任务评估指标失败: {e}")
        return RetUtil.response_error(message=f"对比任务评估指标失败: {e}")


@router.post("/evaluation_export_excel", summary="生成评测结果Excel并上传")
async def evaluation_export_excel(
    evaluation_id: str = Body(..., embed=True, description="评测ID"),
    db: Session = Depends(get_db)
) -> Response:
    """
    根据 evaluation_id 查询数据库内容，生成评测结果 Excel 文件并上传到 MinIO。
    - 参数来源：KnowledgeEvaluationSetting（评测参数与名称）、EvaluationResult（汇总指标）、
                EvaluationAnswer（问题检索详情）、EvaluationQuestion（题目与标准答案）。
    - Excel 写入逻辑复用 service/knowledge_evaluation.py 的 save_to_excel 方法（参考 L285-335）。
    """
    try:
        # 1) 基础参数与存在性校验
        logger.info(f"📝【1】开始生成评测结果Excel文件，评测ID：{evaluation_id}")
        setting: KnowledgeEvaluationSetting | None = db.query(KnowledgeEvaluationSetting).\
            filter(KnowledgeEvaluationSetting.evaluation_id == evaluation_id).first()
        if not setting:
            return RetUtil.response_error(message=f"评测ID {evaluation_id} 不存在")

        # 最新的评测汇总结果
        latest_result: EvaluationResult | None = db.query(EvaluationResult).\
            filter(EvaluationResult.evaluation_id == evaluation_id).\
            order_by(EvaluationResult.update_time.desc()).first()
        if not latest_result:
            return RetUtil.response_error(message=f"评测ID {evaluation_id} 未找到汇总结果")

        file_id = setting.file_id

        # 2) 检索参数（用于 Excel 第一页展示）
        rerank_model = getattr(setting, "rerank_model", "")
        if rerank_id := getattr(setting, "rerank_id", ""):
            rerank_model_data = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                    doc_id=ObjectId(rerank_id),
                )
            if rerank_model_data:
                rerank_model = rerank_model_data.get("model_uid", "") or rerank_model
            # logger.info(f" 💐重排模型model💐: {rerank_model}")
        param = {
            "search_type": setting.search_type,
            "recall_num": setting.recall_num,
            "is_rerank": bool(getattr(setting, "is_rerank", False)),
            "rerank_model": rerank_model or "",
            "rerank_num": getattr(setting, "rerank_num", 0),
            "score": getattr(setting, "score", 0.0),
            "needEnhanceRounds": bool(getattr(setting, "needEnhanceRounds", False)),
            "enhance_rounds": getattr(setting, "enhance_rounds", 0),
            "semantics_weights": getattr(setting, "semantics_weights", 0.0),
            "keywords_weights": getattr(setting, "keywords_weights", 0.0),
            "similarity_threshold": getattr(setting, "similarity_threshold", 0.0),
        }

        # 3) 组装 Excel 第一页的评测结果与参数
        evaluation_time = latest_result.update_time.strftime("%Y-%m-%d %H:%M:%S") if latest_result.update_time else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        eval_payload = {
            "task_name": getattr(setting, "evaluation_name", ""),
            "evaluation_time": evaluation_time,
            # 检索参数
            "search_type": param.get("search_type", "semantic"),
            "recall_num": param.get("recall_num", 10),
            "rerank_model": param.get("rerank_model", "") if param.get("is_rerank") else "",
            "rerank_num": param.get("rerank_num", 0) if param.get("is_rerank") else 0,
            "rerank_threshold": param.get("score", 0.0),
            "enhance_rounds": param.get("enhance_rounds", 0) if param.get("needEnhanceRounds") else 0,
            "fusion_weights": f"{param.get('semantics_weights', 0.0)}:{param.get('keywords_weights', 0.0)}",
            "task_threshold": param.get("similarity_threshold", 0.0),
            # 指标结果
            "recall_k": latest_result.recall_k,
            "mrr": latest_result.mrr,
            "hit_num": latest_result.hit_num,
            "not_hit_num": latest_result.not_hit_num,
        }

        # 4) 第二页数据：答案详情和题目映射
        answer_rows = db.query(EvaluationAnswer).\
            join(EvaluationQuestion, EvaluationAnswer.question_id == EvaluationQuestion.question_id).\
            filter(EvaluationAnswer.evaluation_id == evaluation_id).\
            order_by(EvaluationQuestion.question_index.asc(), EvaluationAnswer.index.asc()).all()
        answers_data = []
        for a in answer_rows:
            answers_data.append({
                "answer_id": a.answer_id,
                "question_id": a.question_id,
                "evaluation_id": a.evaluation_id,
                "chunk_content": a.chunk_content,
                "recall_score": float(getattr(a, "recall_score", 0.0) or 0.0),
                "is_hit": bool(getattr(a, "is_hit", False)),
                "similarity": float(getattr(a, "similarity", 0.0) or 0.0),
                "index": int(getattr(a, "index", 0) or 0),
                "hit_score": float(getattr(a, "hit_score", 0.0) or 0.0),
                "all_hit": bool(getattr(a, "all_hit", False)),
            })

        questions = db.query(EvaluationQuestion).\
            filter(EvaluationQuestion.file_id == file_id).\
            order_by(EvaluationQuestion.question_index.asc()).all()
        qa_map = {q.question_id: {"question": q.question, "standard_answer": q.standard_answer, "question_index": int(getattr(q, "question_index", 0) or 0)} for q in questions}

        # 5) 本地生成 Excel（使用 upload/evaluation_exports 作为输出目录）
        output_dir = Path(__file__).parents[2] / "upload" / "evaluation_exports"
        output_dir.mkdir(parents=True, exist_ok=True)
        # save_to_excel 仅取父目录，文件名随意占位
        placeholder_src = output_dir / f"{file_id}_source.xlsx"
        # logger.info(f"评测结果🌹{eval_payload}")
        # logger.info(f"相似度阈值🌹{param.get('similarity_threshold', 0.0) or 0.0}")

        excel_path = Knowledge_Evaluation_service.save_to_excel(
            evaluation_result=eval_payload, #第一页
            file_path=str(placeholder_src),
            file_id=file_id,
            sheet_name="测评结果",
            answers=answers_data, # 第二页
            qa_map=qa_map,
            hit_threshold=float(param.get("similarity_threshold", 0.0) or 0.0)
        )

        # 6) 上传到 MinIO 并更新 EvaluationResult 的下载地址
        # 获取知识库ID以构造远程路径
        task = db.query(KNOWLEDGE_EVALUATION).filter(KNOWLEDGE_EVALUATION.file_id == file_id).first()
        kb_id = task.kb_id if task else ""
        file_name = os.path.basename(excel_path)
        remote_path = f"evaluation/{kb_id}/{file_name}" if kb_id else f"evaluation/{file_id}/{file_name}"
        bucket_name = "tiance-base"
        await run_in_threadpool(MinIoUtil.upload_file, bucket_name, remote_path, excel_path)

        # 更新所有该评测ID的结果excel的下载地址
        db.query(EvaluationResult).filter(EvaluationResult.evaluation_id == evaluation_id).update({
            EvaluationResult.evaluation_result_url: remote_path,
            EvaluationResult.update_time: datetime.now()
        })
        db.commit()

        return FileResponse(
            excel_path,
            filename=file_name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    except Exception as e:
        logger.exception(f"生成评测结果Excel失败（evaluation_id={evaluation_id}）：{e}")
        if db:
            db.rollback()
        return RetUtil.response_error(message=f"生成评测结果Excel失败：{e}")


@router.post("/evaluation_question", summary="查看命中，未命中内容，查看新增命中，新增未命中内容")
async def evaluation_question(
        payload: dict = Body(...,
                             description="{ evaluation_id, type: '0'|'1'|'2'|'3', from: '<评测ID>', to: '<评测ID>', page?: number, page_size?: number, question?: string }"),
        db: Session = Depends(get_db)
):
    """
    根据输入类型返回问题与检索内容：
    - type='0': 返回指定 evaluation_id 的命中问题及其检索内容
    - type='1': 返回指定 evaluation_id 的未命中问题及其检索内容
    - type='2': 返回相对于 from → to 的新增命中问题（to 命中，但 from 未命中）
    - type='3': 返回相对于 from → to 的新增未命中问题（from 命中，但 to 未命中）
    """
    try:
        logger.info(f"查看命中，未命中内容，查看新增命中，新增未命中内容: {payload}")
        def _get_hit_qids(eval_id: str) -> set[str]:
            rows = db.query(EvaluationAnswer.question_id). \
                filter(EvaluationAnswer.evaluation_id == eval_id, EvaluationAnswer.all_hit == True). \
                distinct().all()
            return {r[0] for r in rows if r and r[0]}

        def _get_not_hit_qids(eval_id: str) -> set[str]:
            all_rows = db.query(EvaluationAnswer.question_id). \
                filter(EvaluationAnswer.evaluation_id == eval_id). \
                distinct().all()
            hit_rows = db.query(EvaluationAnswer.question_id). \
                filter(EvaluationAnswer.evaluation_id == eval_id, EvaluationAnswer.all_hit == True). \
                distinct().all()
            all_qids = {r[0] for r in all_rows if r and r[0]}
            hit_qids = {r[0] for r in hit_rows if r and r[0]}
            return all_qids - hit_qids

        def _build_items(eval_id: str, qids: set[str]) -> list[dict]:
            if not qids:
                return []
            # 题目详情
            questions = db.query(EvaluationQuestion). \
                filter(EvaluationQuestion.question_id.in_(list(qids))).all()
            qmap = {q.question_id: q for q in questions}
            # 检索答案
            items: list[dict] = []
            for qid in qids:
                q = qmap.get(qid)
                answers = db.query(EvaluationAnswer). \
                    filter(EvaluationAnswer.evaluation_id == eval_id, EvaluationAnswer.question_id == qid). \
                    order_by(EvaluationAnswer.index.asc()).all()
                items.append({
                    "question_id": qid,
                    "question": getattr(q, "question", None),
                    "standard_answer": getattr(q, "standard_answer", None),
                })
            return items
        evaluation_id = str(payload.get("evaluation_id", "")).strip()
        view_type = str(payload.get("type", "")).strip()
        from_id = str(payload.get("from", "")).strip()
        to_id = str(payload.get("to", "")).strip()

        if view_type in ("0", "1") and not evaluation_id:
            return RetUtil.response_error(message="type 为 0/1 时，evaluation_id 必填")
        if view_type in ("2", "3") and (not from_id or not to_id):
            return RetUtil.response_error(message="type 为 2/3 时，from 和 to 必填")

        result_qids: set[str] = set()
        eval_for_items: str = evaluation_id  # 构建详情时使用的评测ID

        if view_type == "0":
            # 命中问题（evaluation_id）
            result_qids = _get_hit_qids(evaluation_id)
            eval_for_items = evaluation_id
        elif view_type == "1":
            # 未命中问题（evaluation_id）
            result_qids = _get_not_hit_qids(evaluation_id) 
            eval_for_items = evaluation_id
        elif view_type == "2":
            # 新增命中问题（from → to）to命中-from命中
            to_hit_qids = _get_hit_qids(to_id)
            from_hit_qids = _get_hit_qids(from_id)
            result_qids = to_hit_qids - from_hit_qids
            eval_for_items = to_id
        elif view_type == "3":
            # 新增未命中问题（from → to）
            to_not_hit_qids = _get_not_hit_qids(to_id)
            from_not_hit_qids = _get_not_hit_qids(from_id)
            result_qids = to_not_hit_qids - from_not_hit_qids
            eval_for_items = to_id
        else:
            return RetUtil.response_error(message="type 取值无效，应为 '0'|'1'|'2'|'3'")

        page = int(str(payload.get("page", 1)).strip() or 1)
        page_size = int(str(payload.get("page_size", 10)).strip() or 10)
        if page < 1 or page_size < 1:
            return RetUtil.response_error(message="page 和 page_size 必须大于 0")

        items_all = _build_items(eval_for_items, result_qids)
        query = str(payload.get("question", "")).strip()
        if query:
            scored = []
            for item in items_all:
                q_text = item.get("question") or ""
                if not q_text:
                    continue
                if q_text == query:
                    scored.append((item, 2))
                elif query in q_text:
                    scored.append((item, 1))
            scored.sort(key=lambda x: x[1], reverse=True)
            items_all = [it for it, _ in scored]

        offset = (page - 1) * page_size
        end = offset + page_size
        items_page = items_all[offset:end]

        response_data = {
            "type": view_type,
            "page": page,
            "page_size": page_size,
            "total": len(items_all),
            "result": items_page,
            "evaluation_id": eval_for_items,
        }
        if view_type in ("2", "3"):
            response_data["from_id"] = from_id
            response_data["to_id"] = to_id
        return RetUtil.response_ok(data=response_data)
    except Exception as e:
        logger.exception(f"查看评测问题失败（payload={payload}）：{e}")
        return RetUtil.response_error(message=f"查看评测问题失败：{e}")
