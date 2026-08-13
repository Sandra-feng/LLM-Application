
import ast
import asyncio
import datetime
import json
import os
import re
import time
import traceback
import uuid
from pathlib import Path
from zipfile import ZipFile

from bson import ObjectId
from fastapi import HTTPException, requests
from fastapi.concurrency import run_in_threadpool
from loguru import logger
from sqlalchemy.orm import Session

from base_configs.minio_config import MinioConfig
from base_configs.mongodb_config import CollectionConfig
from base_utils.milvus_util import MilvusUtil
from base_utils.minio_util import MinIoUtil
from base_utils.mongodb_util import MongodbUtil
from base_utils.page_util import PageUtil
from base_utils.redis_util import RedisUtil
from base_utils.ret_util import RetUtil
from service_knowledge_manage.service.knowledge_service import KnowledgeService
from service_model_manage.entity.chat_completion_entity import (
    ChatCompletionRequestParams,
)
from service_model_manage.service.chat_completion_service import OpenAILLMService
from service_model_manage.service.model_family_service import ModelFamilyService
from service_permission_auth.model.team_mem_model import TeamMem_Model
from service_permission_auth.model.team_model import Team_Model
from service_prompt_manage.service.prompt_service import PromptService
from service_synonym_manage.api.routes.synonym_group_route import get_synonym_group
from service_toolset_manage.service.toolset_service import Toolset_service
from service_usr_manage.service.snow_util import generate_unique_id


# logger = loguru logger (auto-migrated)
class AgentService:
    # @staticmethod
    # async def agent_has_tool_or_kb_import(agent_content_dict: dict):
    #     """
    #     判断该智能体文件是否有工具或者知识库
    #     :param agent_content_dict: 智能体基础数据与编排数据
    #     :return:
    #     """
    #     try:
    #         has_tool = False
    #         has_kb = False
    #         if not agent_content_dict.get("agent_arrange"):
    #             return {"has_tool": has_tool, "has_kb": has_kb, "mode": "import"}
    #         if agent_content_dict["agent_arrange"].get("tool_list"):
    #             has_tool = True
    #         if agent_content_dict["agent_arrange"].get("kb_list"):
    #             has_kb = True
    #         return {"has_tool": has_tool, "has_kb": has_kb, "mode": "import"}
    #
    #     except Exception as e:
    #         LogUtil.error(f"查询智能体文件是否有工具或者知识库 异常: {str(traceback.format_exc())}")
    #         raise e

    @staticmethod
    async def agent_has_tool_or_kb_export(agent_id: str):
        """
        判断该智能体是否有工具或者知识库
        :param agent_id: 智能体id
        :return: 一个字典判断是否有工具或者知识库
        """
        try:
            # 查询智能体的编排信息
            cursor = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.ARRANGE_AGENT_COLLECTION, search_condition={"_id": ObjectId(agent_id)}
            )
            agent_arrange = dict({})
            for doc in cursor:
                agent_arrange = doc

            has_tool = False
            has_kb = False
            if not agent_arrange:
                return {"has_tool": has_tool, "has_kb": has_kb, "mode": "export"}

            if agent_arrange.get("tool_list", None):
                has_tool = True
            if agent_arrange.get("kb_list", None):
                has_kb = True
            return {"has_tool": has_tool, "has_kb": has_kb, "mode": "export"}

        except Exception:
            raise

    @staticmethod
    async def agent_import(
        file_obj, is_save_kn: bool, is_save_tool: bool, account_id: str, team_code: str, db: Session
    ):
        track_information_dict = dict({})
        try:
            track_information_dict["complete_knowledge"] = []
            track_information_dict["complete_tool"] = []
            track_information_dict["complete_agent"] = []

            temp_id = generate_unique_id("Temp", datacenter_id=1, worker_id=1)
            temp_folder = Path(__file__).parents[2] / "upload" / "temp_import" / temp_id
            os.makedirs(temp_folder, exist_ok=True)

            # 保存上传的文件到临时文件夹
            temp_zip_path = temp_folder / file_obj.filename
            with open(temp_zip_path, "wb") as temp_file:
                temp_file.write(await file_obj.read())

            # 解压上传的文件
            with ZipFile(temp_zip_path, "r") as zip_ref:
                zip_ref.extractall(temp_folder)

            if temp_zip_path.exists():
                os.remove(temp_zip_path)

            if not os.path.exists(temp_folder / "output.json"):
                raise HTTPException(detail="上传的配置文件中无json文件，请重新上传", status_code=400)

            with open(temp_folder / "output.json", encoding="utf-8") as json_file:
                agent_content_dict = json.load(json_file)

            if team_code is None:
                team_code = ""

            create_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # 插入智能体基础信息到MongoDB
            agent_content_dict["agent_doc"]["agent_name"] += "_导入"
            agent_content_dict["agent_doc"]["create_time"] = create_time
            agent_content_dict["agent_doc"]["account_id"] = account_id
            agent_content_dict["agent_doc"]["status"] = 0
            agent_content_dict["agent_doc"]["team_code"] = team_code
            agent_content_dict["agent_arrange"]["account_id"] = account_id

            # 限制插入的表单的格式
            std_agent = [
                "agent_name",
                "description",
                "create_time",
                "account_id",
                "team_code",
                "type_name",
                "code",
                "status",
            ]
            std_agent_arrange = [
                "model_params",
                "prompt",
                "recall_setting",
                "kb_list",
                "tool_list",
                "account_id",
                "variable_list",
                "promptHtml",
                "prompt_id",
            ]
            agent_key = [key for key in agent_content_dict["agent_doc"].keys()]
            for k in agent_key:
                if k not in std_agent:
                    agent_content_dict["agent_doc"].pop(k, None)
                # 限制长度
                elif k == "description" and len(agent_content_dict["agent_doc"].get(k)) > 500:
                    raise Exception("description过长，不应超过500词")
                elif (
                    k != "description"
                    and isinstance(agent_content_dict["agent_doc"].get(k), str)
                    and len(agent_content_dict["agent_doc"].get(k)) > 100
                ):
                    raise Exception("{}过长".format(k))
            agent_arrange_key = [key for key in agent_content_dict["agent_arrange"].keys()]
            for k in agent_arrange_key:
                if k not in std_agent_arrange:
                    agent_content_dict["agent_arrange"].pop(k, None)
                elif k in ["prompt", "promptHtml"] and len(agent_content_dict["agent_arrange"].get(k)) > 10000:
                    raise Exception("{}过长，不应超过10000词".format(k))
                elif (
                    k not in ["prompt", "kb_list", "tool_list"]
                    and isinstance(agent_content_dict["agent_arrange"].get(k), str)
                    and len(agent_content_dict["agent_arrange"].get(k)) > 100
                ):
                    raise Exception("{}过长".format(k))

            logger.info(
                "开始插入智能体，{}深拷贝工具，{}深拷贝知识库。".format(
                    "需要" if is_save_tool else "不需要", "需要" if is_save_kn else "不需要"
                )
            )

            # 深度复制一份prompt
            prompt_id_old = agent_content_dict["agent_arrange"].get("prompt_id", "")
            if prompt_id_old:
                # 如果prompt_id存在且不为空，则复制一份提示词
                prompt_id_new = PromptService.copy_prompt_by_id(
                    db=db,
                    prompt_id_old=prompt_id_old,
                    prompt_name="草稿",
                    agent_id="wait_for_update",
                    workflow_id="",
                    account_id=account_id,
                    team_code=team_code,
                    status=2,
                )
            else:
                prompt_id_new = ""
            agent_content_dict["agent_arrange"]["prompt_id"] = prompt_id_new

            # 插入智能体编排信息到MongoDB
            # 是否需要深拷贝工具
            tool_report = {
                "tool_admin": [],
                "tool_exist": [],
                "tool_delete": [],
                "tool_deep_copy": [],
                "mcp_tool_success": [],
                "tool_error": [],
            }
            kb_report = {"kb_exist": [], "kb_delete": [], "kb_deep_copy": []}
            agent_content_dict, tool_report, track_information_dict = await AgentService.tool_import(
                is_save_tool, agent_content_dict, tool_report, team_code, account_id, db, track_information_dict
            )
            # 是否需要深拷贝知识库
            agent_content_dict, kb_report, track_information_dict = await AgentService.knowledge_import(
                is_save_kn,
                agent_content_dict,
                kb_report,
                team_code,
                account_id,
                temp_folder,
                temp_id,
                track_information_dict,
            )

            # 插入智能体基础信息表和编排表
            agent_id_new, track_information_dict = await AgentService.agent_import2(
                agent_content_dict, track_information_dict
            )

            # 若前段代码有插入prompt信息，更新agent_id
            if prompt_id_new:
                update_agent_result = PromptService.update_agent_by_prompt_id(
                    db=db, prompt_id=prompt_id_new, agent_id=agent_id_new
                )
                logger.info("成功复制了一个提示词，id为{}".format(update_agent_result))
            else:
                prompt = agent_content_dict["agent_arrange"].get("prompt", "")
                if prompt:
                    try:
                        prompt_id_new = PromptService.create_prompt_id_by_prompt(
                            db=db,
                            prompt=prompt,
                            prompt_name="草稿",
                            agent_id=agent_id_new,
                            workflow_id="",
                            account_id=account_id,
                            team_code=team_code,
                            status=2,
                        )

                        MongodbUtil.update_docs_by_condition(
                            CollectionConfig.ARRANGE_AGENT_COLLECTION,
                            search_condition={"_id": ObjectId(agent_id_new)},
                            replace_data={"$set": {"prompt_id": prompt_id_new}},
                        )
                    except:
                        raise
            # 处理返回信息
            report_m = ""
            temp_report = ""
            for tool_admin in tool_report["tool_admin"]:
                temp_report += " {} ".format(tool_admin)
            if temp_report != "":
                report_m += "工具{}为内置工具，直接使用\n".format(temp_report)

            temp_report = ""
            for tool_exist in tool_report["tool_exist"]:
                temp_report += " {} ".format(tool_exist)
            if temp_report != "":
                report_m += "工具{}已经存在，直接使用\n".format(temp_report)

            temp_report = ""
            for tool_deep_copy in tool_report["tool_deep_copy"]:
                temp_report += " {} ".format(tool_deep_copy)
            if temp_report != "":
                report_m += "工具{}成功复制\n".format(temp_report)

            temp_report = ""
            for tool_delete in tool_report["tool_delete"]:
                temp_report += " {} ".format(tool_delete)
            if temp_report != "":
                report_m += "id为{}的工具不存在\n".format(temp_report)

            temp_report = ""
            for kb_exist in kb_report["kb_exist"]:
                temp_report += " {} ".format(kb_exist)
            if temp_report != "":
                report_m += "知识库{}已经存在，直接使用\n".format(temp_report)

            temp_report = ""
            for kb_deep_copy in kb_report["kb_deep_copy"]:
                temp_report += " {} ".format(kb_deep_copy)
            if temp_report != "":
                report_m += "知识库{}成功复制\n".format(temp_report)

            temp_report = ""
            for kb_delete in kb_report["kb_delete"]:
                temp_report += " {} ".format(kb_delete)
            if temp_report != "":
                report_m += "id为{}的知识库不存在\n".format(temp_report)

            return temp_folder, report_m
        except Exception as e:
            await AgentService.agent_traceback(track_information_dict)
            raise

        except HTTPException as he:
            track_information_dict = he.headers
            await AgentService.agent_traceback(track_information_dict)
            raise HTTPException(detail=he.detail, status_code=he.status_code)

    @staticmethod
    async def agent_export(agent_id: str, is_save_kn: bool, is_save_tool: bool):
        """
        导出智能体
        :param agent_id: 智能体id
        :param is_save_kn: 保存知识库数据
        :param is_save_tool: 保存工具数据
        :return: 是否导出成功
        """
        try:
            original_agent = {}
            # 查询智能体的基础信息
            agent_doc = MongodbUtil.query_doc_by_id(
                collection_name=CollectionConfig.AGENT_COLLECTION, doc_id=ObjectId(agent_id)
            )
            if not agent_doc:
                raise HTTPException(detail="智能体基础信息不存在，请检查输入参数配置", status_code=400)

            # 复制基础信息并插入新文档
            agent_doc.pop("_id", None)
            agent_doc["status"] = 0

            # 查询智能体的编排信息
            agent_arrange = MongodbUtil.query_doc_by_id(
                collection_name=CollectionConfig.ARRANGE_AGENT_COLLECTION, doc_id=ObjectId(agent_id)
            )
            if not agent_arrange:
                raise HTTPException(detail="智能体编排信息不存在，请检查输入参数配置", status_code=400)

            agent_arrange.pop("_id", None)
            # 若选择不保存知识库或者工具，则置空
            if not is_save_kn:
                agent_arrange["kb_list"] = []
            if not is_save_tool:
                agent_arrange["tool_list"] = []
            agent_arrange["kb_result"] = []

            original_agent["agent_doc"] = agent_doc
            original_agent["agent_arrange"] = agent_arrange

            # 生成唯一标识ID，存放知识库导出的所有文件
            temp_id = generate_unique_id("Temp", datacenter_id=1, worker_id=1)

            # 如果有知识库需要导出，则对知识库列表进行遍历，对每一个知识库id进行数据导出
            for kb_id in agent_arrange["kb_list"]:
                # 知识库导出
                output_json = await AgentService.knowledge_whole_export(kb_id, temp_id)
                original_agent[kb_id] = output_json

            # 如果有工具需要导出，对工具列表进行遍历，获取每一个工具的信息
            for tool_info in agent_arrange["tool_list"]:
                # 适配新旧格式
                if isinstance(tool_info, list) and len(tool_info) == 3:
                    tool_type, _, _ = tool_info  # tool_info:["system", "1"/"0", "tool_id"]
                    # 只导出system类型工具的详细信息, mcp工具会在导入的时候单独处理
                    if tool_type != "system_tools":
                        continue
                    else:
                        tool_id = tool_info[2]
                elif isinstance(tool_info, str):
                    # 兼容旧格式
                    tool_id = tool_info
                else:
                    continue

                original_agent[tool_id] = {}
                # 工具信息导出
                tool_doc = MongodbUtil.query_doc_by_id(collection_name=CollectionConfig.TOOL_COLLECTION, doc_id=tool_id)
                if tool_doc:
                    original_agent[tool_id]["tool_info"] = tool_doc
                else:
                    raise HTTPException(detail="工具id配置错误，请检查工具参数", status_code=400)
                tool_config_info = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.TOOL_INFO_COLLECTION, doc_id=tool_id
                )
                if tool_config_info:
                    original_agent[tool_id]["tool_config_info"] = tool_config_info
                else:
                    raise HTTPException(detail="工具id配置错误，请检查工具参数", status_code=400)

            # 保存json文件
            # json文件内容： agent_doc: {}
            #          agent_arrange: {}
            #          kb_id: {}
            #          tool_id: {}
            local_folder = Path(__file__).parents[2] / "upload" / temp_id
            os.makedirs(local_folder, exist_ok=True)
            json_file_path = local_folder / "output.json"
            with open(json_file_path, "w", encoding="utf-8") as json_file:
                json.dump(original_agent, json_file, ensure_ascii=False, indent=4)

            # 保存压缩包文件
            # 压缩包文件内容
            # kb_id -- minio远程文件服务器文件
            zip_file_path = Path(__file__).parents[2] / "upload" / f"{temp_id}.zip"
            with ZipFile(zip_file_path, "w") as zipf:
                for root, dirs, files in os.walk(local_folder):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, local_folder)
                        zipf.write(file_path, arcname)

            return zip_file_path

        except HTTPException as he:
            raise he

        except Exception as e:
            raise e

    @staticmethod
    async def handle_system_tool_import(
        tool_id: str,
        is_builtin: bool,
        agent_content_dict: dict,
        tool_report: dict,
        team_code: str,
        account_id: str,
        db: Session,
        track_information_dict: dict,
        tool_index_id: int,
    ):
        """处理系统工具导入（保持原有逻辑）"""
        tool_info = agent_content_dict[tool_id]["tool_info"]
        tool_q = tool_info

        # 如果是管理员工具，则不用复制
        user_attribute = await ModelFamilyService.get_user_attribute_by_account_id(db, tool_q.get("account_id"))
        # 这里多加了一个判断条件是因为如果在其他环境中导入管理员工具，
        # 需要user_attribute为1且工具表中有这个工具才能说明这个工具为管理员工具，否则还是作为普通工具进行拷贝
        if user_attribute and MongodbUtil.query_doc_by_id(
            collection_name=CollectionConfig.TOOL_COLLECTION, doc_id=tool_id
        ):
            logger.info("工具{}是管理员工具，直接使用".format(tool_id))
            tool_report["tool_admin"].append(tool_q.get("tool_name"))
            return True, tool_id

        # 源工具是属于目标用户或目标团队，不用复制
        if tool_q is not None:
            tool_instance = MongodbUtil.query_doc_by_id(
                collection_name=CollectionConfig.TOOL_COLLECTION, doc_id=tool_id
            )
            if team_code == "":
                # 对于个人工具的处理情况
                if (
                    tool_instance
                    and tool_instance["account_id"] == account_id
                    and tool_instance.get("account_id", "") == team_code
                ):
                    logger.info("个人工具{}不能自己导入自己".format(tool_id))
                    tool_report["tool_exist"].append(tool_q.get("tool_name"))
                    return True, tool_id
            else:
                # 对于团队工具的情况
                if tool_instance and tool_instance.get("account_id", "") == team_code:
                    logger.info("团队工具{}不能自己导入自己".format(tool_id))
                    tool_report["tool_exist"].append(tool_q.get("tool_name"))
                    return True, tool_id
        else:
            # 这个工具在工具库中找不到
            logger.info("工具{}不存在，取消复制".format(tool_id))
            tool_report["tool_delete"].append(tool_id)
            return False, None

        # 源工具已经在目标用户或者目标团队导入过一次，不用再复制
        if team_code == "":
            tool_f = MongodbUtil.query_docs_by_condition(
                CollectionConfig.TOOL_COLLECTION,
                {"from_tool": tool_id, "account_id": account_id, "team_code": team_code},
            )
        else:
            tool_f = MongodbUtil.query_docs_by_condition(
                CollectionConfig.TOOL_COLLECTION, {"from_tool": tool_id, "team_code": team_code}
            )
        ori_tool = dict({})
        for doc in tool_f:
            ori_tool = doc
        if ori_tool:
            if team_code == "":
                logger.info("个人工具{}不能重复导入".format(tool_id))
            else:
                logger.info("团队工具{}不能重复导入".format(tool_id))
            tool_report["tool_exist"].append(ori_tool.get("tool_name"))
            return True, ori_tool.get("_id")

        # 复制工具
        tool_dict = agent_content_dict[tool_id]
        new_tool_id, ori_name = await Toolset_service.copy_tool_by_info(
            tool_dict=tool_dict, account_id=account_id, team_code=team_code, status=1
        )

        if new_tool_id != "":
            track_information_dict["complete_tool"].append(new_tool_id)
            tool_report["tool_deep_copy"].append(ori_name)
            logger.info("插入了一个工具，原工具id为{}，新工具id为{}".format(tool_id, new_tool_id))
            return True, new_tool_id
        else:
            raise Exception("工具导入失败")

    @staticmethod
    async def handle_mcp_tools_batch_import(
        server_id: str,
        tool_items: list,  # [(tool_index_id, tool_name), ...]
        agent_content_dict: dict,
        tool_report: dict,
        team_code: str,
        account_id: str,
        db: Session,
        track_information_dict: dict,
        new_tool_list: list,
    ):
        """批量处理 MCP 工具导入 - 避免重复处理同一个 MCP 服务"""
        try:
            # 1. 通过 MCP 服务 ID 查找 MCP 服务实例（只查询一次）
            mcp_service_instance = MongodbUtil.query_doc_by_id(
                collection_name=CollectionConfig.OUTSIDE_MCP_CONFIG, doc_id=server_id
            )

            if not mcp_service_instance:
                logger.warning(f"MCP服务 {server_id} 不存在")
                for tool_index_id, tool_name in tool_items:
                    tool_report["tool_error"].append(f"MCP服务 {server_id} 不存在")
                return

            # 2. 验证所有工具是否存在于该 MCP 服务中
            service_tools = {tool.get("tool_name"): tool for tool in mcp_service_instance.get("tool_list", [])}
            valid_tools = []

            for tool_index_id, tool_name in tool_items:
                if tool_name in service_tools:
                    valid_tools.append((tool_index_id, tool_name, service_tools[tool_name]))
                else:
                    logger.warning(f"工具 {tool_name} 不在 MCP 服务 {server_id} 中")
                    tool_report["tool_error"].append(f"工具 {tool_name} 不在 MCP 服务 {server_id} 中")

            if not valid_tools:
                logger.info(f"MCP服务 {server_id} 没有有效工具需要导入")
                return

            # 3. 检查 MCP 服务归属（只检查一次）
            is_same_owner = False
            if team_code == "":
                # 个人工具：检查 account_id 是否匹配
                if mcp_service_instance.get("account_id") == account_id:
                    is_same_owner = True
                    logger.info(f"MCP服务 {server_id} 属于目标用户，直接使用")
                    for tool_index_id, tool_name, _ in valid_tools:
                        tool_report["mcp_tool_success"].append(f"MCP工具 {tool_name}")
                        new_tool_list.append(["mcp_tools", server_id, tool_name])
            else:
                # 团队工具：检查 team_code 是否匹配
                if mcp_service_instance.get("team_code") == team_code:
                    is_same_owner = True
                    logger.info(f"MCP服务 {server_id} 属于目标团队，直接使用")
                    for tool_index_id, tool_name, _ in valid_tools:
                        tool_report["mcp_tool_success"].append(f"MCP工具 {tool_name}")
                        new_tool_list.append(["mcp_tools", server_id, tool_name])

            if is_same_owner:
                return  # 直接使用原有服务，无需复制

            # 4. 检查目标用户是否已有同名的 MCP 服务（只查询一次）
            existing_mcp_cursor = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.OUTSIDE_MCP_CONFIG,
                search_condition={
                    "name": mcp_service_instance["name"],
                    **({"account_id": account_id} if team_code == "" else {"team_code": team_code}),
                },
            )
            # 将 Cursor 转换为列表并取第一个文档（如果存在）
            existing_mcp_list = list(existing_mcp_cursor)
            existing_mcp = existing_mcp_list[0] if existing_mcp_list else None

            if existing_mcp:
                # 检查现有 MCP 服务是否已包含目标工具
                existing_tool_names = {tool.get("tool_name") for tool in existing_mcp.get("tool_list", [])}

                need_update_tools = []
                new_tools_for_existing = []

                for tool_index_id, tool_name, target_tool in valid_tools:
                    if tool_name in existing_tool_names:
                        logger.info(f"目标用户已有包含工具 {tool_name} 的 MCP 服务")
                        tool_report["mcp_tool_success"].append(f"MCP工具 {tool_name}")
                        new_tool_list.append(["mcp_tools", existing_mcp["_id"], tool_name])
                    else:
                        need_update_tools.append(target_tool)
                        new_tools_for_existing.append((tool_index_id, tool_name))

                if need_update_tools:
                    # 批量更新现有 MCP 服务的工具列表（只更新一次）
                    updated_tool_list = existing_mcp.get("tool_list", [])
                    updated_tool_list.extend(need_update_tools)

                    MongodbUtil.update_one_doc(
                        collection_name=CollectionConfig.OUTSIDE_MCP_CONFIG,
                        doc_id=existing_mcp["_id"],
                        update_data={"tool_list": updated_tool_list},
                    )

                    logger.info(f"更新现有 MCP 服务 {existing_mcp['_id']} 添加 {len(need_update_tools)} 个工具")
                    for tool_index_id, tool_name in new_tools_for_existing:
                        tool_report["mcp_tool_success"].append(f"MCP工具 {tool_name}")
                        new_tool_list.append(["mcp_tools", existing_mcp["_id"], tool_name])

                return

            # 5. 需要复制 MCP 服务（只复制一次，包含所有需要的工具）
            _id = generate_unique_id("MCP_", datacenter_id=1, worker_id=1)
            new_mcp_service = {
                "_id": _id,
                "name": mcp_service_instance["name"],
                "url": mcp_service_instance["url"],
                "timeout": mcp_service_instance.get("timeout", 30),
                "headers": mcp_service_instance.get("headers", []),
                "account_id": account_id if team_code == "" else "",
                "team_code": team_code if team_code != "" else "",
                "upload_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": True,
                "tool_list": mcp_service_instance.get("tool_list", []),
            }

            MongodbUtil.insert_one(collection_name=CollectionConfig.OUTSIDE_MCP_CONFIG, doc_content=new_mcp_service)

            logger.info(f"复制 MCP 服务 {_id} 包含 {len(valid_tools)} 个工具")
            for tool_index_id, tool_name, _ in valid_tools:
                tool_report["mcp_tool_success"].append(f"MCP工具 {tool_name}")
                new_tool_list.append(["mcp_tools", _id, tool_name])

        except Exception as e:
            logger.exception(f"批量处理 MCP 工具导入失败: {str(e)}")
            for tool_index_id, tool_name in tool_items:
                tool_report["tool_error"].append(f"MCP工具 {tool_name} 导入失败")

    @staticmethod
    async def tool_import(
        is_save_tool: bool,
        agent_content_dict: dict,
        tool_report: dict,
        team_code: str,
        account_id: str,
        db: Session,
        track_information_dict: dict,
    ):
        try:
            if not is_save_tool:
                agent_content_dict["agent_arrange"]["tool_list"] = []
            else:
                logger.info("共有{}个工具需要导入".format(len(agent_content_dict["agent_arrange"]["tool_list"])))
                new_tool_list = []
                tool_delete_index = []

                # 第一步：分类收集工具信息
                system_tools = []
                mcp_tools = {}  # 按 server_id 分组

                for tool_index_id, tool_info in enumerate(agent_content_dict["agent_arrange"]["tool_list"]):
                    # 适配新旧格式
                    if isinstance(tool_info, list) and len(tool_info) == 3:
                        # 新格式：["system_tools"/"mcp_tools", "tool_id"/"server_id", "is_builtin"/"tool_name"]
                        tool_type, _, _ = tool_info
                    elif isinstance(tool_info, str):
                        # 兼容旧格式：["tool_id"]
                        tool_type, tool_id, tool_param = "system", tool_info, ""
                    else:
                        # 无效格式
                        logger.warning(f"无效的工具格式: {tool_info}")
                        tool_delete_index.append(tool_index_id)
                        tool_report["tool_error"].append("工具格式无效")
                        continue

                    if tool_type == "system_tools":
                        # 收集系统工具
                        is_builtin = tool_info[1]
                        tool_id = tool_info[2]
                        system_tools.append((tool_index_id, is_builtin, tool_id))
                    elif tool_type == "mcp_tools":
                        # 收集 MCP 工具，按 server_id 分组
                        tool_name = tool_info[2]
                        tool_id = tool_info[1]
                        if tool_id not in mcp_tools:
                            mcp_tools[tool_id] = []
                        mcp_tools[tool_id].append((tool_index_id, tool_name))
                    else:
                        logger.warning(f"未知的工具类型: {tool_type}")
                        tool_delete_index.append(tool_index_id)
                        tool_report["tool_error"].append(f"工具类型 {tool_type} 不支持")

                # 第二步：处理系统工具
                for tool_index_id, is_builtin, tool_id in system_tools:
                    success, result_tool_id = await AgentService.handle_system_tool_import(
                        tool_id,
                        is_builtin,
                        agent_content_dict,
                        tool_report,
                        team_code,
                        account_id,
                        db,
                        track_information_dict,
                        tool_index_id,
                    )
                    if success and result_tool_id:
                        new_tool_list.append(["system_tools", "1" if is_builtin else "0", result_tool_id])

                # 第三步：批量处理 MCP 工具
                for server_id, tool_list in mcp_tools.items():
                    await AgentService.handle_mcp_tools_batch_import(
                        server_id,
                        tool_list,
                        agent_content_dict,
                        tool_report,
                        team_code,
                        account_id,
                        db,
                        track_information_dict,
                        new_tool_list,
                    )

                # 更新工具列表为新格式
                agent_content_dict["agent_arrange"]["tool_list"] = new_tool_list

            return agent_content_dict, tool_report, track_information_dict

        except Exception as e:
            logger.exception(f"工具导入失败: {str(e)}")
            raise HTTPException(detail="工具导入失败", status_code=400, headers=track_information_dict)

    @staticmethod
    async def knowledge_import(
        is_save_kn: bool,
        agent_content_dict: dict,
        kb_report: dict,
        team_code: str,
        account_id: str,
        temp_folder: Path,
        temp_id: str,
        track_information_dict: dict,
    ):
        try:
            if not is_save_kn:
                agent_content_dict["agent_arrange"]["kb_list"] = []
            else:
                logger.info("共有{}个知识库需要拷贝".format(len(agent_content_dict["agent_arrange"]["kb_list"])))
                kb_delete_index = []
                for kb_index_id in range(len(agent_content_dict["agent_arrange"]["kb_list"])):
                    kb_id = agent_content_dict["agent_arrange"]["kb_list"][kb_index_id]
                    kb_q = agent_content_dict[kb_id]["knowledge_info"]

                    # 源知识库是属于目标用户或目标团队，不用复制
                    if kb_q is not None:
                        # 查找知识库中是否存在改知识库id的知识库，如果有不进行导入
                        kb_instance = MongodbUtil.query_doc_by_id(
                            collection_name=CollectionConfig.KB_COLLECTION, doc_id=ObjectId(kb_id)
                        )
                        if team_code == "":
                            if (
                                kb_instance
                                and kb_instance.get("account_id", "") == account_id
                                and kb_instance.get("team_code", "") == team_code
                            ):
                                logger.info("个人知识库{}不能自己导入自己".format(kb_id))
                                kb_report["kb_exist"].append(kb_q.get("kb_name"))
                                continue
                        else:
                            if kb_instance and kb_instance.get("team_code", "") == team_code:
                                logger.info("团队知识库{}不能自己导入自己".format(kb_id))
                                kb_report["kb_exist"].append(kb_q.get("kb_name"))
                                continue
                    else:
                        # 这个知识库不存在
                        logger.info("知识库{}不存在，取消复制".format(kb_id))
                        kb_delete_index.append(kb_index_id)
                        kb_report["kb_delete"].append(kb_id)
                        continue

                    # 源知识库已经在目标用户或者目标团队导入过一次，不用再复制
                    if team_code == "":
                        kb_f = MongodbUtil.query_docs_by_condition(
                            CollectionConfig.KB_COLLECTION,
                            {"from_kb": kb_id, "account_id": account_id, "team_code": team_code},
                        )
                    else:
                        kb_f = MongodbUtil.query_docs_by_condition(
                            CollectionConfig.KB_COLLECTION, {"from_kb": kb_id, "team_code": team_code}
                        )
                    ori_kb = dict({})
                    for doc in kb_f:
                        ori_kb = doc
                    if ori_kb:
                        logger.info("知识库{}不能重复导入".format(kb_id))
                        agent_content_dict["agent_arrange"]["kb_list"][kb_index_id] = str(ori_kb.get("_id"))
                        kb_report["kb_exist"].append(ori_kb.get("kb_name"))
                        continue

                    # 复制知识库
                    # 遍历解压后的文件夹
                    result = {"json_content": None, "files": []}
                    result["json_content"] = agent_content_dict[kb_id]
                    extracted_folder_path = temp_folder / kb_id
                    for root, dirs, files in os.walk(extracted_folder_path):
                        for file in files:
                            file_path = Path(root) / file
                            result["files"].append(str(file_path.relative_to(temp_folder)))
                    new_kb_id, ori_name = await AgentService.knowledge_whole_import(
                        result, account_id, team_code, temp_id
                    )
                    if kb_id != "":
                        track_information_dict["complete_knowledge"].append(new_kb_id)
                        agent_content_dict["agent_arrange"]["kb_list"][kb_index_id] = new_kb_id
                        kb_report["kb_deep_copy"].append(ori_name)
                        logger.info("插入了一个知识库，原知识库id为{}，新知识库id为{}".format(kb_id, new_kb_id))
                    else:
                        raise Exception("发生逻辑错误")
                # 若在知识库库中找不到对应的知识库，则不复制智能体的知识库索引
                for delete_index in reversed(kb_delete_index):
                    del agent_content_dict["agent_arrange"]["kb_list"][delete_index]

            return agent_content_dict, kb_report, track_information_dict

        except Exception:
            raise HTTPException(detail="知识库导入失败", status_code=400, headers=track_information_dict)

    @staticmethod
    async def agent_import2(agent_content_dict: dict, track_information_dict: dict):
        try:
            insert_result = MongodbUtil.insert_one(CollectionConfig.AGENT_COLLECTION, agent_content_dict["agent_doc"])
            agent_id_new = str(insert_result.inserted_id)
            track_information_dict["complete_agent"].append(agent_id_new)
            agent_content_dict["agent_arrange"]["_id"] = ObjectId(agent_id_new)
            model_uid = agent_content_dict["agent_arrange"]["model_params"]["model_uid"]
            model_info = {"model_uid": model_uid}
            _id, model_name = await AgentService.query_info_by_model_info(model_info)
            if _id and model_name:
                agent_content_dict["agent_arrange"]["model_params"]["id"] = _id
                agent_content_dict["agent_arrange"]["model_params"]["model_name"] = model_name
                logger.info("插入智能体信息时查询到LLM模型信息")
            else:
                agent_content_dict["agent_arrange"]["model_params"]["id"] = ""
                agent_content_dict["agent_arrange"]["model_params"]["model_name"] = ""
                agent_content_dict["agent_arrange"]["model_params"]["model_uid"] = ""
                logger.info("插入智能体信息时未查询到LLM模型id，信息置空")
            if agent_content_dict["agent_arrange"]["recall_setting"]["is_rerank"]:
                model_uid = agent_content_dict["agent_arrange"]["recall_setting"]["rerank_model"]
                model_info = {"model_uid": model_uid}
                _id, model_name = await AgentService.query_info_by_model_info(model_info)
                if _id and model_name:
                    agent_content_dict["agent_arrange"]["recall_setting"]["rerank_id"] = _id
                    agent_content_dict["agent_arrange"]["recall_setting"]["rerank_name"] = model_name
                    logger.info("插入智能体信息时查询到重排模型信息")
                else:
                    agent_content_dict["agent_arrange"]["recall_setting"]["rerank_id"] = ""
                    agent_content_dict["agent_arrange"]["recall_setting"]["rerank_name"] = ""
                    agent_content_dict["agent_arrange"]["recall_setting"]["rerank_model"] = ""
                    agent_content_dict["agent_arrange"]["recall_setting"]["is_rerank"] = False
                    logger.info("插入智能体信息时未查询到重排模型信息，信息置空")
            MongodbUtil.insert_one(CollectionConfig.ARRANGE_AGENT_COLLECTION, agent_content_dict["agent_arrange"])
            logger.info("成功插入一条智能体基础信息和编排信息，id为{}".format(agent_id_new))
            return agent_id_new, track_information_dict

        except Exception:
            raise HTTPException(detail="智能体导入失败", status_code=400, headers=track_information_dict)

    @staticmethod
    async def agent_traceback(track_information_dict: dict):
        try:
            for kb_id in track_information_dict["complete_knowledge"]:
                # 删除知识库基本信息
                MongodbUtil.del_doc_by_id(collection_name=CollectionConfig.KB_COLLECTION, doc_id=ObjectId(kb_id))
                logger.info(f"知识库基本信息表数据删除成功，知识库id为《《{kb_id}》》")

                # 删除minio文件夹
                folder_prefix = f"{kb_id}/"

                def delete_minio_files(folder_prefix):
                    objects = MinIoUtil.get_file_list(MinioConfig.BUCKET_NAME, prefix=folder_prefix)
                    for obj in objects:
                        file_name = os.path.basename(obj)
                        if file_name:
                            MinIoUtil.delete_file(MinioConfig.BUCKET_NAME, obj)
                        else:
                            delete_minio_files(obj)

                delete_minio_files(folder_prefix)
                logger.info(f"知识库id为《《{kb_id}》》远程文件删除成功")

                # 删除向量数据库
                milvus = MilvusUtil()
                await milvus.drop_collection(collection_name=f"_{kb_id}")
                logger.info(f"知识库id为《《{kb_id}》》向量数据库删除成功")

                # 删除上传文件信息表信息
                MongodbUtil.del_docs_by_condition(
                    collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION, del_condition={"knowledge_id": kb_id}
                )
                logger.info(f"知识库id为《《{kb_id}》》上传文件信息删除成功")

            for tool_id in track_information_dict["complete_tool"]:
                # 删除基本信息
                MongodbUtil.del_doc_by_id(collection_name=CollectionConfig.TOOL_COLLECTION, doc_id=tool_id)
                logger.info(f"工具id为《《{tool_id}》》基本信息删除成功")
                # 删除配置信息
                MongodbUtil.del_doc_by_id(collection_name=CollectionConfig.TOOL_INFO_COLLECTION, doc_id=tool_id)
                logger.info(f"工具id为《《{tool_id}》》配置信息删除成功")

            for agent_id in track_information_dict["complete_agent"]:
                # 删除基本信息
                MongodbUtil.del_doc_by_id(collection_name=CollectionConfig.AGENT_COLLECTION, doc_id=ObjectId(agent_id))
                logger.info(f"智能体id为《《{agent_id}》》基本信息删除成功")
                # 删除编排信息
                MongodbUtil.del_doc_by_id(
                    collection_name=CollectionConfig.ARRANGE_AGENT_COLLECTION, doc_id=ObjectId(agent_id)
                )
                logger.info(f"智能体id为《《{agent_id}》》编排信息删除成功")
            logger.info("智能体回溯成功")

        except Exception:
            raise

    @staticmethod
    async def create_agent(agent_name, desripition, account_id, code, type_name):
        try:
            agent_id = ""
            create_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if code == "":
                code = "0"
                type_name = "其他"
            insert_result = MongodbUtil.insert_one(
                CollectionConfig.AGENT_COLLECTION,
                {
                    "agent_name": agent_name,
                    "description": desripition,
                    "create_time": create_time,
                    "account_id": account_id,
                    "status": 0,
                    "code": code,
                    "type_name": type_name,
                },
            )
            if insert_result is not None:
                agent_id = str(insert_result.inserted_id)
                model_info = await AgentService.running_LLM_model()
                model_info = (
                    model_info[0]
                    if len(model_info) != 0
                    else {"model_name": "", "id": "", "model_uid": "", "is_external": "", "max_tokens": 0}
                )
                model_params = {
                    "id": model_info["id"],
                    "model_uid": model_info["model_uid"],
                    "model_name": model_info["model_name"],
                    "max_token_length": model_info["max_tokens"],
                    "temperature": 0.8,
                    "history": 3,
                    "presence_penalty": 0,
                    "frequency_penalty": 0,
                }
                prompt = ""
                promptHtml = ""
                recall_setting = {
                    "is_rerank": False,
                    "rerank_id": None,
                    "rerank_model": "",
                    "rerank_name": "",
                    "top_k": 1,
                    "score": 0.8,
                }
                kb_list = list([])
                tool_list = list([])
                variable_list = list([])
                await AgentService.arrange_agent(
                    agent_id=agent_id,
                    account_id=account_id,
                    model_params=model_params,
                    prompt=prompt,
                    recall_setting=recall_setting,
                    kb_list=kb_list,
                    tool_list=tool_list,
                    variable_list=variable_list,
                    promptHtml=promptHtml,
                    prompt_id="",
                    is_question_rewriting=False,
                )
            return "新增智能体成功", agent_id

        except Exception as e:
            raise

    @staticmethod
    async def copy_agent(agent_id: str, db: Session) -> bool:
        """
        复制智能体
        :param agent_id: 原智能体ID
        :param db: 数据库对象
        :return: 新智能体ID或错误信息
        """
        try:
            # 查询原智能体的基础信息
            cursor = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.AGENT_COLLECTION, search_condition={"_id": ObjectId(agent_id)}
            )
            original_agent = dict({})
            for doc in cursor:
                original_agent = doc

            # 查询原智能体的编排信息
            cursor = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.ARRANGE_AGENT_COLLECTION, search_condition={"_id": ObjectId(agent_id)}
            )
            original_arrange_info = dict({})
            for doc in cursor:
                original_arrange_info = doc.copy()
                original_arrange_info.pop("_id", None)

            # 复制基础信息并插入新文档
            doc_copy = original_agent.copy()
            doc_copy.pop("_id", None)  # 移除原始 ID
            # 设置复制智能体名称
            original_name = doc_copy["agent_name"]
            pattern = re.compile(f"^{re.escape(original_name)}（副本(\\d+)）$")
            cursor = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.AGENT_COLLECTION, search_condition={"from_id": agent_id}
            )
            max_index = 0
            for doc in cursor:
                match = pattern.match(doc.get("agent_name", ""))
                if match:
                    num = int(match.group(1))
                    if num > max_index:
                        max_index = num
            new_index = max_index + 1
            new_name = f"{original_name}（副本{new_index}）"

            new_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            doc_copy["agent_name"] = new_name
            doc_copy["create_time"] = new_time
            doc_copy["from_id"] = agent_id
            doc_copy["status"] = 0

            # 复制prompt
            # 深度复制一份prompt
            prompt_id_new = ""
            if original_arrange_info != {}:
                prompt_id_old = original_arrange_info.get("prompt_id", "")
                if prompt_id_old:
                    # 如果prompt_id存在且不为空，则复制一份提示词
                    prompt_id_new = PromptService.copy_prompt_by_id(
                        db=db,
                        prompt_id_old=prompt_id_old,
                        prompt_name="草稿",
                        agent_id="wait_for_update",
                        workflow_id="",
                        account_id=original_arrange_info.get("account_id", ""),
                        team_code=original_arrange_info.get("team_code", ""),
                        status=2,
                    )
                original_arrange_info["prompt_id"] = prompt_id_new

            insert_result = MongodbUtil.insert_one(CollectionConfig.AGENT_COLLECTION, doc_copy)
            new_agent_id = insert_result.inserted_id
            logger.info(f"新智能体基础信息插入成功，ID: {new_agent_id}")

            if original_arrange_info != {}:
                # 更新编排信息中的 agent_id 和 account_id
                original_arrange_info["_id"] = ObjectId(new_agent_id)
                # 插入新编排信息
                arrange_result = MongodbUtil.insert_one(
                    CollectionConfig.ARRANGE_AGENT_COLLECTION, original_arrange_info
                )
                # 更新前段代码插入的prompt信息
                if prompt_id_new:
                    update_agent_result = PromptService.update_agent_by_prompt_id(
                        db=db, prompt_id=prompt_id_new, agent_id=new_agent_id
                    )
                    logger.info("成功复制了一个提示词，id为{}".format(update_agent_result))

                if arrange_result:
                    logger.info(f"智能体编排信息复制成功，新智能体ID: {new_agent_id}")
                else:
                    logger.info("复制编排信息失败")
                    return False
            else:
                logger.info("原智能体没有编排信息，跳过编排信息复制")

            return True

        except Exception as e:
            return False

    @staticmethod
    async def delete_agent(agent_id):
        try:
            MongodbUtil.del_docs_by_condition(CollectionConfig.AGENT_COLLECTION, {"_id": ObjectId(agent_id)})
            MongodbUtil.del_docs_by_condition(CollectionConfig.ARRANGE_AGENT_COLLECTION, {"_id": ObjectId(agent_id)})
            return "删除智能体成功"
        except Exception:
            raise

    @staticmethod
    async def arrange_agent(
        agent_id,
        account_id,
        model_params,
        prompt,
        recall_setting,
        kb_list,
        tool_list,
        variable_list,
        promptHtml,
        prompt_id,
        is_question_rewriting,
    ):
        try:
            result = MongodbUtil.query_docs_by_condition(
                CollectionConfig.ARRANGE_AGENT_COLLECTION, search_condition={"_id": ObjectId(agent_id)}
            )
            for _ in result:
                MongodbUtil.update_one(
                    CollectionConfig.ARRANGE_AGENT_COLLECTION,
                    {"_id": ObjectId(agent_id)},
                    update_operation={
                        "$set": {
                            "model_params": model_params,
                            "prompt": prompt,
                            "recall_setting": recall_setting,
                            "kb_list": kb_list,
                            "tool_list": tool_list,
                            "account_id": account_id,
                            "variable_list": variable_list,
                            "promptHtml": promptHtml,
                            "prompt_id": prompt_id,
                            "is_question_rewriting": is_question_rewriting,
                        }
                    },
                )
                return "更新编排智能体成功"
            else:
                MongodbUtil.insert_one(
                    CollectionConfig.ARRANGE_AGENT_COLLECTION,
                    {
                        "_id": ObjectId(agent_id),
                        "model_params": model_params,
                        "prompt": prompt,
                        "recall_setting": recall_setting,
                        "kb_list": kb_list,
                        "tool_list": tool_list,
                        "account_id": account_id,
                        "variable_list": variable_list,
                        "promptHtml": promptHtml,
                        "prompt_id": prompt_id,
                        "is_question_rewriting": is_question_rewriting,
                    },
                )
                return "首次创建编排智能体成功"

        except Exception as e:
            raise

    @staticmethod
    async def test_agent(params):
        try:
            result = MongodbUtil.query_docs_by_condition(
                CollectionConfig.ARRANGE_AGENT_COLLECTION, search_condition={"_id": ObjectId(params.agent_id)}
            )
            for item in result:
                model_uid = item["model_uid"]
                prompt = item["prompt"]
                kb_list = item["kb_list"]
                tool_list = item["tool_list"]

            prompt_tool = f"""
    # 角色
    你是一个精通各种工具的专家，能够准确地分析问题并选择合适的工具来解决。

    您可以使用的工具如下:{tool_list}
    ## 技能
    ### 技能 1: 工具匹配
    1. 当用户提出问题时，仔细分析问题需求，匹配可用工具。



    """
            if len(tool_list) > 0:
                prompt_tool = prompt_tool
            # 业务逻辑处理
            openAILLMService = OpenAILLMService()
            response_content = ""
            result = openAILLMService.chunk_chat(
                request=ChatCompletionRequestParams(
                    question=params.input,
                    system_prompts=prompt_tool,
                    chatbot=[],
                    history=3,
                    max_token_length=4096,
                    temperature=0.8,
                    model_uid=model_uid,
                )
            )
            logger.info(f"大模型输出工具为:{result}")
            return result
        except Exception:
            raise

    @staticmethod
    async def use_agent(params):
        try:
            result = MongodbUtil.query_docs_by_condition(
                CollectionConfig.ARRANGE_AGENT_COLLECTION, search_condition={"_id": ObjectId(params.agent_id)}
            )
            for item in result:
                model_uid = item["model_uid"]

                prompt_tool = """
                # 角色
                你是一个能够准确判断用户意图的智能体。
                ## 技能
                ### 技能
                1：判断用户意图 
                1. 仔细分析用户的问题。 
                2. 如果用户问的是时间问题，在 JSON 格式中，"params"字段返回为"获取时区时间"。 
                3. 如果用户问的是天气相关问题，"params"字段返回为"获取时区时间"。 
                4. 如果既不是问时间也不是问天气，"params"字段则为"获取地区天气"。
                ## 限制 - 严格按照 JSON 格式输出结果。 - 只根据用户问题判断意图，不进行其他无关操作。   
                """

                example_prompt = """
                    ## 样例:
                    样例一：
                    问题:长沙市天气怎么样
                    输出:{'params': '获取地区天气'}
                    样例二：
                    问题:今天多少号
                    输出:{'params': '获取时区时间'}
                    样例
                """

                prompt_tool = prompt_tool + example_prompt
                # 业务逻辑处理
                openAILLMService = OpenAILLMService()
                result = openAILLMService.chunk_chat(
                    request=ChatCompletionRequestParams(
                        question=params.input,
                        system_prompts=prompt_tool,
                        chatbot=[],
                        history=3,
                        max_token_length=4096,
                        temperature=0.8,
                        model_uid=model_uid,
                    )
                )
                logger.info(f"大模型输出工具为:{result}")
                return json.loads(str(result))
        except Exception as e:
            raise

    @staticmethod
    async def get_first_running_model():
        try:
            # 获取运行中、非推理、未删除的LLM模型
            non_inference_model = MongodbUtil.query_docs_by_condition(
                CollectionConfig.MODEL_RUN_COLLECTION,
                {
                    "model_type": "LLM",
                    "status": "running",
                    "is_think": False,
                    "is_delete": False,
                    "is_external": False,
                    "modalities": {"$exists": True, "$nin": ["image"]},
                },
            )
            for model in non_inference_model:
                # 返回第一个符合条件模型的id与uid
                logger.info(f"调用的LLM模型id为{model['_id']},LLM模型模型名称为{model['model_uid']}")
                return str(model["_id"]), model["model_uid"]

            # 如果没有运行中、非推理、未删除的LLM模型，那就搜索运行中、推理、未删除的LLM模型
            inference_model = MongodbUtil.query_docs_by_condition(
                CollectionConfig.MODEL_RUN_COLLECTION,
                {
                    "model_type": "LLM",
                    "status": "running",
                    "is_think": True,
                    "is_delete": False,
                    "is_external": False,
                    "modalities": {"$exists": True, "$nin": ["image"]},
                },
            )
            for model in inference_model:
                # 返回第一个符合条件模型的id与uid
                logger.info(f"调用的LLM模型id为{model['_id']},LLM模型名称为{model['model_uid']}")
                return str(model["_id"]), model["model_uid"]

            # 若没有符合上面两个条件的数据，搜索没有来得及添加is_inference的运行中、未删除的LLM模型
            models = MongodbUtil.query_docs_by_condition(
                CollectionConfig.MODEL_RUN_COLLECTION,
                {"model_type": "LLM", "status": "running", "is_delete": False, "is_external": False},
            )
            for model in models:
                # 返回第一个符合条件模型的id与uid
                logger.info(f"调用的LLM模型id为{model['_id']},LLM模型名称为{model['model_uid']}")
                return str(model["_id"]), model["model_uid"]

            models = MongodbUtil.query_docs_by_condition(
                CollectionConfig.MODEL_RUN_COLLECTION,
                {"model_type": "LLM", "status": "running", "is_think": False, "is_delete": False, "is_external": True},
            )
            for model in models:
                # 返回第一个符合条件模型的id与uid
                logger.info(f"调用的LLM模型id为{model['_id']},LLM模型名称为{model['model_uid']}")
                return str(model["_id"]), model["model_uid"]

            models = MongodbUtil.query_docs_by_condition(
                CollectionConfig.MODEL_RUN_COLLECTION,
                {"model_type": "LLM", "status": "running", "is_think": True, "is_delete": False, "is_external": True},
            )
            for model in models:
                # 返回第一个符合条件模型的id与uid
                logger.info(f"调用的LLM模型id为{model['_id']},LLM模型名称为{model['model_uid']}")
                return str(model["_id"]), model["model_uid"]

            return False, False

        except Exception:
            return False, False

    @staticmethod
    async def get_running_model_list(model_type: str):
        try:
            external_model_list = []
            internal_model_list = []
            # 获取运行中、外部模型
            external_model = MongodbUtil.query_docs_by_condition(
                CollectionConfig.MODEL_RUN_COLLECTION,
                {"model_type": model_type, "status": "running", "is_delete": False, "is_external": True},
            )
            for model in external_model:
                model_info = {
                    "model_name": model["model_name"] if model.get("model_name", None) else model["model_uid"],
                    "id": str(model["_id"]),
                    "model_uid": model["model_uid"],
                    "is_external": model["is_external"],
                    "modalities": model.get("modalities", ""),
                }
                if model_type == "embedding":
                    dimension = model["max_model_len"]
                    model_info["dimension"] = dimension
                    model_info["max_tokens"] = model["max_tokens"]
                if model_type == "LLM":
                    model_info["max_tokens"] = model["max_tokens"]
                external_model_list.append(model_info)

            # 如果没有运行中、内部模型
            internal_model = MongodbUtil.query_docs_by_condition(
                CollectionConfig.MODEL_RUN_COLLECTION,
                {"model_type": model_type, "status": "running", "is_delete": False, "is_external": False},
            )
            for model in internal_model:
                model_info = {
                    "model_name": model["model_uid"],
                    "id": str(model["_id"]),
                    "model_uid": model["model_uid"],
                    "is_external": model["is_external"],
                    "modalities": model.get("modalities", ""),
                }
                if model_type == "embedding":
                    result = MongodbUtil.query_doc_by_id(
                        collection_name=CollectionConfig.MODEL_FAMILY_COLLECTION, doc_id=model["model_id"]
                    )
                    dimension = result["model_emb_details"]["model_embedding_dimension"]
                    model_info["dimension"] = dimension
                    model_info["max_tokens"] = result["model_emb_details"].get("model_contex_length", None)
                if model_type == "LLM":
                    model_info["max_tokens"] = model.get("max_tokens", None)
                internal_model_list.append(model_info)

            return {"name": "内部", "children": internal_model_list}, {"name": "外部", "children": external_model_list}

        except Exception as e:
            return [], []

    @staticmethod
    async def running_LLM_model():
        try:
            results = []
            result = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.MODEL_RUN_COLLECTION, search_condition={}
            )
            for item in result:
                if item["status"] == "running" and item["model_type"] == "LLM" and item["is_delete"] == False:
                    if item["is_external"] == False:
                        data = {
                            "model_name": item["model_uid"],
                            "id": str(item["_id"]),
                            "model_uid": item["model_uid"],
                            "is_external": item["is_external"],
                            "max_tokens": item.get("max_tokens", 8192),
                        }
                    else:
                        data = {
                            "model_name": item["model_name"],
                            "id": str(item["_id"]),
                            "model_uid": item["model_uid"],
                            "is_external": item["is_external"],
                            "max_tokens": item.get("max_tokens", 8192),
                        }
                    results.append(data)
            return results
        except Exception as e:
            raise

    @staticmethod
    async def agent_arrange_info(chat_request, agent_id, db):
        try:
            logger.info(f"->查询智能体{agent_id}的发布状态")
            synonym_info_list = []
            result_info = MongodbUtil.query_doc_by_id(
                collection_name=CollectionConfig.AGENT_COLLECTION, doc_id=ObjectId(agent_id)
            )
            status = result_info.get("status")
            assert status is not None, "查询不到发布状态"
            logger.info("智能体{}{}发布".format(agent_id, "已" if status else "未"))
            logger.info("->查询智能体编排信息")
            result = MongodbUtil.query_doc_by_id(
                collection_name=CollectionConfig.ARRANGE_AGENT_COLLECTION, doc_id=ObjectId(agent_id)
            )
            synonym_binding_info = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.SYNONYM_BINDING, search_condition={"id": agent_id, "type": 0}
            )
            for item in synonym_binding_info:
                synonym_binding_list = item["synonym_id_list"]
                for synonym_id in synonym_binding_list:
                    synonym_info = await get_synonym_group(chat_request=chat_request, id=synonym_id, db=db)
                    response_body = synonym_info.body
                    response_str = response_body.decode()
                    response_result = json.loads(response_str)
                    synonym_info = response_result["data"]
                    synonym_info_list.append(synonym_info)
            if result is None:
                return False
            if result["model_params"].get("presence_penalty", None) is None:
                result["model_params"]["presence_penalty"] = 0
            if result["model_params"].get("frequency_penalty", None) is None:
                result["model_params"]["frequency_penalty"] = 0
            return {
                "model_params": result["model_params"],
                "prompt": result["prompt"],
                "recall_setting": result["recall_setting"],
                "kb_list": result["kb_list"],
                "tool_list": result["tool_list"],
                "account_id": result["account_id"],
                "variable_list": result.get("variable_list", []),
                "promptHtml": result.get("promptHtml", ""),
                "prompt_id": result.get("prompt_id", ""),
                "status": status,
                "synonym_info_list": synonym_info_list,
                "is_question_rewriting": result.get("is_question_rewriting", False),
            }
        except Exception:
            raise

    @staticmethod
    async def agent_exist(agent_name: str, account_id: str):
        try:
            condition = {"agent_name": agent_name, "account_id": account_id}
            agent = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.ARRANGE_AGENT_COLLECTION, search_condition=condition
            )
            for _ in agent:
                return True
            return False
        except Exception as e:
            raise

    @staticmethod
    async def query_agent(agent_name, page, page_size, account_id, code, id, status=None):
        try:
            from datetime import datetime

            status_condition = []
            if status is not None:
                status_condition = [{"status": status}]
            try:
                if code != "":
                    if id != "":
                        condition = {
                            "$and": [
                                {
                                    "$or": [
                                        {"agent_name": {"$regex": rf"{re.escape(agent_name)}(\_.*)?", "$options": "i"}},
                                        {
                                            "description": {
                                                "$regex": rf"{re.escape(agent_name)}(\_.*)?",
                                                "$options": "i",
                                            }
                                        },
                                    ]
                                },
                                {"code": code},
                                {"account_id": account_id},
                                {"_id": ObjectId(id)},
                                {
                                    "$or": [
                                        {"team_code": {"$exists": False}},
                                        {"team_code": {"$eq": None}},
                                        {"team_code": {"$eq": ""}},
                                    ]
                                },
                            ]
                            + status_condition
                        }
                    else:
                        condition = {
                            "$and": [
                                {
                                    "$or": [
                                        {"agent_name": {"$regex": rf"{re.escape(agent_name)}(\_.*)?", "$options": "i"}},
                                        {
                                            "description": {
                                                "$regex": rf"{re.escape(agent_name)}(\_.*)?",
                                                "$options": "i",
                                            }
                                        },
                                    ]
                                },
                                {"code": code},
                                {"account_id": account_id},
                                {
                                    "$or": [
                                        {"team_code": {"$exists": False}},
                                        {"team_code": {"$eq": None}},
                                        {"team_code": {"$eq": ""}},
                                    ]
                                },
                            ]
                            + status_condition
                        }
                else:
                    if id != "":
                        condition = {
                            "$and": [
                                {
                                    "$or": [
                                        {"agent_name": {"$regex": rf"{re.escape(agent_name)}(\_.*)?", "$options": "i"}},
                                        {
                                            "description": {
                                                "$regex": rf"{re.escape(agent_name)}(\_.*)?",
                                                "$options": "i",
                                            }
                                        },
                                    ]
                                },
                                {"account_id": account_id},
                                {"_id": ObjectId(id)},
                                {
                                    "$or": [
                                        {"team_code": {"$exists": False}},
                                        {"team_code": {"$eq": None}},
                                        {"team_code": {"$eq": ""}},
                                    ]
                                },
                            ]
                            + status_condition
                        }
                    else:
                        condition = {
                            "$and": [
                                {
                                    "$or": [
                                        {"agent_name": {"$regex": rf"{re.escape(agent_name)}(\_.*)?", "$options": "i"}},
                                        {
                                            "description": {
                                                "$regex": rf"{re.escape(agent_name)}(\_.*)?",
                                                "$options": "i",
                                            }
                                        },
                                    ]
                                },
                                {"account_id": account_id},
                                {
                                    "$or": [
                                        {"team_code": {"$exists": False}},
                                        {"team_code": {"$eq": None}},
                                        {"team_code": {"$eq": ""}},
                                    ]
                                },
                            ]
                            + status_condition
                        }
            except:
                return {"total": 0, "result": []}
            result = []
            results = MongodbUtil.query_docs_by_condition_pagination(
                CollectionConfig.AGENT_COLLECTION,
                search_condition=condition,
                page=page,
                page_size=page_size,
                sort_field="create_time",
            )
            len_result = MongodbUtil.count_documents_by_condition(CollectionConfig.AGENT_COLLECTION, condition)

            def parse_upload_time(upload_time_str):
                return datetime.strptime(upload_time_str, "%Y-%m-%d %H:%M:%S")

            for item in results:
                temp = item.get("code", "")

                # 查询是否发布为mcp
                is_mcp_tool = False
                mcp_instance = MongodbUtil.query_docs_by_condition(
                    CollectionConfig.INSIDE_MCP_CONFIG, search_condition={"mcp_id": str(item["_id"])}
                )
                for mcp_item in mcp_instance:
                    is_mcp_tool = mcp_item.get("is_mcp_tool", False)

                result.append(
                    {
                        "agent_id": str(item["_id"]),
                        "agent_name": item["agent_name"],
                        "description": item["description"],
                        "account_id": item["account_id"],
                        "status": item["status"],
                        "code": temp,
                        "is_mcp_tool": is_mcp_tool,
                    }
                )
            return {"total": len_result, "result": result}
        except Exception:
            raise

    @staticmethod
    async def list_knowledge_test(account_id):
        try:
            results = []
            result = MongodbUtil.query_docs_by_condition(
                CollectionConfig.KB_COLLECTION, search_condition={"account_id": account_id}
            )
            for item in result:
                results.append(item["kb_name"])
            # return RetUtil.return_ok(result)
            return results
        except Exception as e:
            raise

    @staticmethod
    async def update_agent(agent_id, agent_name, description, code):
        try:
            result = MongodbUtil.query_docs_by_condition(
                CollectionConfig.AGENT_COLLECTION, search_condition={"_id": ObjectId(agent_id)}
            )
            logger.info(f"查询智能体搜索结果: {result}")
            for item in result:
                MongodbUtil.update_one(
                    CollectionConfig.AGENT_COLLECTION,
                    query_filter={"_id": ObjectId(agent_id)},
                    update_operation={
                        "$set": {
                            "agent_name": agent_name,
                            "description": description,
                            "code": code,
                        }
                    },
                )
            return "更新智能体基础信息成功"

        except Exception as e:
            return False

    @staticmethod
    async def tool_query_by_user(account_id_list: list[str] = [], team_codes: list[str] = None):
        """
        查询用户工具列表（支持多个个人工具和多个团队工具）
        :param account_id_list: 用户ID列表
        :param tool_name: 工具名称（支持模糊查询）
        :param team_codes: 团队ID列表（如果为空，则仅查询个人工具）
        :return: 工具列表
        """
        try:
            search_condition = {}
            # 构建查询条件
            query_conditions = []
            if team_codes is not None and len(team_codes) > 0:
                # 当team_codes存在且非空时，添加team_code的查询条件
                team_condition = {"team_code": {"$in": team_codes}}
                query_conditions.append(team_condition)
            else:
                # 当team_codes不存在或为空时，添加team_code为空的条件
                team_condition = {"team_code": ""}
                query_conditions.append(team_condition)

                # 同时，添加account_id的条件
                if account_id_list:
                    personal_condition = {"account_id": {"$in": account_id_list}}
                    query_conditions.append(personal_condition)
            state_condition = {"status": 1}
            query_conditions.append(state_condition)

            if not query_conditions:
                logger.info("无法查询")
                return []
            # 使用 $and 操作符合并条件
            search_condition["$and"] = query_conditions
            tool_list = MongodbUtil.query_docs_by_condition(
                CollectionConfig.TOOL_COLLECTION, search_condition=search_condition
            )
            result = []
            for tool in tool_list:
                # 查询一次获取所有所需字段
                tool_doc = MongodbUtil.query_doc_by_id(CollectionConfig.TOOL_INFO_COLLECTION, doc_id=str(tool["_id"]))
                properties_list = tool_doc.get("properties_list", [])
                url = tool_doc.get("url", "")
                method = tool_doc.get("method", "")
                media_type = tool_doc.get("media_type", "")
                description = tool_doc.get("description", "")
                tool_result = tool_doc.get("result", None)

                tool_info = {
                    "_id": str(tool["_id"]),
                    "tool_name": tool["tool_name"],
                    "description": description,
                    "properties_list": properties_list,
                    "url": url,
                    "method": method,
                    "media_type": media_type,
                    "credentials": tool["credentials"],
                    "result": tool_result,
                }
                result.append(tool_info)
            return result  # 直接返回结果列表
        except Exception as e:
            return RetUtil.response_error(message="查询工具失败")

    @staticmethod
    async def whether_use_tool(input, model_params, tool_list):
        try:
            prompt_tool = f"""
                # 角色
                你是一个精通多种工具的专家，能精准分析问题并选择合适的工具来解决。

                可用工具列表: {tool_list}

                ## 技能
                1. 分析用户问题，判断是否需要使用工具。
                2. 如果需要使用工具，返回True；否则返回False,不需要输出其他任何别的东西。
                """

            # 业务逻辑处理
            openAILLMService = OpenAILLMService()
            result = openAILLMService.chunk_chat(
                request=ChatCompletionRequestParams(
                    question=input,
                    system_prompts=prompt_tool,
                    chatbot=[],
                    history=3,
                    max_token_length=4096,
                    temperature=0.8,
                    model_uid=model_params["model_uid"],
                )
            )
            logger.info(f"大模型意图识别为:{result}")
            return result
        except Exception as e:
            raise

    @staticmethod
    async def tool_list(result):
        try:
            tool_list = []
            for tool in result["tool_list"]:
                tool_info = MongodbUtil.query_doc_by_id(CollectionConfig.TOOL_COLLECTION, doc_id=tool)
                if tool_info.get("status") != 1:  # 如果工具未发布（status不等于1），跳过该工具
                    continue
                tool_config = MongodbUtil.query_doc_by_id(CollectionConfig.TOOL_INFO_COLLECTION, doc_id=tool)
                # schema = tool_result["schema"]
                # logger.info(f"schema{schema}")
                # schema = json.loads(schema)
                # servers = schema.get('servers', [])
                # if servers:
                #     url = servers[0].get('url', '')
                # else:
                #     url = ""
                #
                # # 提取路径和操作
                # paths = schema.get('paths', {})
                # if paths:
                #     path = next(iter(paths), None)  # 获取第一个路径
                #     if path:
                #         operations = paths[path]  # 获取该路径下的所有操作（如 post, get 等）
                #         method = next(iter(operations), None)  # 获取第一个操作方法
                #         if method:
                #             operation_details = operations[method]  # 获取操作的详细信息
                #             summary = operation_details.get('summary', '')
                #             operation_id = operation_details.get('operationId', '')
                #             request_body = operation_details.get('requestBody', {})
                #             properties = request_body.get('content', {}).get('application/json', {}).get('schema',
                #                                                                                          {}).get(
                #                 'properties', {})
                #             required = request_body.get('content', {}).get('application/json', {}).get('schema',
                #                                                                                        {}).get(
                #                 'required', [])
                tool_url = tool_config["url"]
                # tool_url = url + path
                tool_parm = {
                    "type": "function",
                    "function": {
                        "name": tool_config["tool_name"],
                        "description": tool_config["description"],
                        "parameters": {
                            "type": "object",
                            "properties": tool_config["properties_list"],
                            "required": [
                                param["name"] for param in tool_config["properties_list"] if param["required"]
                            ],
                        },
                    },
                }
                method = tool_config["method"]
                tool_list.append({"tool_parm": tool_parm, "tool_url": tool_url, "method": method})

            return tool_list
        except Exception:
            raise

    @staticmethod
    async def generate_tool_function(tool_info):
        tool_name = tool_info["tool_parm"]["function"]["name"]
        tool_url = tool_info["tool_url"]
        tool_method = tool_info["method"]

        async def tool_function(**kwargs):
            headers = {"Content-Type": "application/json"}
            logger.info(f"接口{tool_url}调用了")
            max_retries = 3  # 最大重试次数
            retry_delay = 2  # 重试间隔（秒）
            for attempt in range(max_retries):
                try:
                    logger.info(f"尝试调用接口: {tool_url}, 尝试次数 {attempt + 1}/{max_retries}")
                    response = requests.request(
                        tool_method,
                        tool_url,
                        headers=headers,
                        json=kwargs,
                        timeout=3,  # 设置超时时间为3秒
                    )
                    if response.status_code == 200:
                        result = response.json()
                        logger.info(f"{tool_name}接口的返回值是:{result}")
                        return result
                    else:
                        logger.info(f"接口调用出错: {response.status_code}")
                        return f"接口调用出错: {response.status_code}"
                except (requests.Timeout, requests.RequestException) as e:
                    logger.info(f"接口调用超时或发生网络错误: {str(e)}，正在重试，尝试次数 {attempt + 1}/{max_retries}")
                    time.sleep(retry_delay)
                except Exception as e:
                    logger.info(f"接口调用发生异常: {str(e)}，正在重试，尝试次数 {attempt + 1}/{max_retries}")
                    time.sleep(retry_delay)
            # 如果所有重试都失败，返回一个明确的错误信息
            # 如果所有重试都失败，返回一个明确的错误信息
            return "接口调用失败，达到最大重试次数"

        return tool_function

    @staticmethod
    async def tool_agent(chat_request, params, model_params, TOOLS, tool_list):
        from qwen_agent.llm import get_chat_model

        async def generate_tool_function(tool_info):
            import asyncio

            import aiohttp

            tool_name = tool_info["tool_parm"]["function"]["name"]
            tool_url = tool_info["tool_url"]
            tool_method = tool_info["method"]
            token = chat_request.headers.get("token", None)

            if token == None:
                redis = chat_request.app.state.redis_pool
                account_id = chat_request.state.account_id
                token_info = await RedisUtil.get_cached_data(key=account_id, redis=redis)
                if token_info != None:
                    token = token_info["value"]

            # if 'token' in chat_request.headers:
            #     token = chat_request.headers.get("token")
            # else:
            #     token = chat_request.headers.get("postman-token")

            async def tool_function(**kwargs):
                headers = {"token": token, "Content-Type": "application/json"}
                logger.info(f"接口{tool_url}调用了")
                max_retries = 3  # 最大重试次数
                retry_delay = 0.3  # 重试间隔（秒）
                result = []
                for attempt in range(max_retries):
                    try:
                        logger.info(f"尝试调用接口: {tool_url}, 尝试次数 {attempt + 1}/{max_retries}")

                        # 设置超时时间为3秒
                        timeout = aiohttp.ClientTimeout(total=3)
                        async with aiohttp.ClientSession(timeout=timeout) as session:
                            async with session.request(tool_method, tool_url, headers=headers, json=kwargs) as response:
                                if response.status == 200:
                                    result.append(await response.json())
                                    logger.info(f"{tool_name}接口的返回值是:{result}")
                                    return result

                                else:
                                    result.append(f"接口调用出错: {response.status}")
                                    logger.info(f"接口调用出错: {response.status}")
                                    return result
                    except (TimeoutError, aiohttp.ClientError) as e:
                        logger.info(
                            f"接口调用超时或发生网络错误: {str(e)}，正在重试，尝试次数 {attempt + 1}/{max_retries}"
                        )
                        await asyncio.sleep(retry_delay)
                    except Exception as e:
                        logger.info(f"接口调用发生异常: {str(e)}，正在重试，尝试次数 {attempt + 1}/{max_retries}")
                        await asyncio.sleep(retry_delay)

                # 如果所有重试都失败，返回一个明确的错误信息
                return "接口调用失败，达到最大重试次数"

            return tool_function

        MESSAGES = [
            {"role": "system", "content": "你是一个有帮助的助手。\n"},
            {"role": "user", "content": params.input},
        ]
        from base_configs.model_config import ModelConfig

        result = MongodbUtil.query_doc_by_id(
            collection_name=CollectionConfig.MODEL_RUN_COLLECTION, doc_id=ObjectId(model_params["id"])
        )

        if result["is_external"] == True:
            llm = get_chat_model(
                {
                    "model": model_params["model_uid"],
                    "model_server": result["api_url"],
                    "api_key": result["api_key"],
                }
            )

        else:
            llm = get_chat_model(
                {
                    "model": model_params["model_uid"],
                    "model_server": ModelConfig.LLM_API_BASE,
                    "api_key": ModelConfig.LLM_API_KEY,
                }
            )

        messages = MESSAGES[:]
        functions = [tool["function"] for tool in TOOLS]
        for responses in llm.chat(
            messages=messages,
            functions=functions,
            extra_generate_cfg=dict(parallel_function_calls=True),
        ):
            pass
        messages.extend(responses)
        tool_use = False
        # 遍历消息列表
        for message in responses:
            # 检查消息中是否有function_call字段
            if "function_call" in message:
                fn_call = message["function_call"]
                # 检查function_call中的name是否不为空
                if fn_call.get("name", "").strip() != "":
                    tool_use = True
                    break  # 如果找到一个非空的fn_name，直接设置tool_use为True并退出循环

        if tool_use == True:
            try:
                # 生成工具函数并添加到 FUNCTION_MAP
                FUNCTION_MAP = {}
                for tool_info in tool_list:
                    tool_name = tool_info["tool_parm"]["function"]["name"]
                    FUNCTION_MAP[tool_name] = await generate_tool_function(tool_info)

                # 定义其他必要的函数和逻辑
                async def get_function_by_name(name):
                    return FUNCTION_MAP.get(name)

                for message in responses:
                    if fn_call := message.get("function_call", None):
                        fn_name: str = fn_call["name"]
                        fn_args: dict = json.loads(fn_call["arguments"])
                        fn_res: str = json.dumps(await (await get_function_by_name(fn_name))(**fn_args))
                        try:
                            fn_res = json.loads(fn_res)
                        except:
                            fn_res = fn_res
                        messages.append(
                            {
                                "role": "function",
                                "name": fn_name,
                                "content": fn_res,
                            }
                        )
            except:
                tool_use = False
        result = messages

        return result, tool_use

    @staticmethod
    async def intention_recognition(query, system_prompt, model_params, tool_list):
        # try:
        import json
        import re

        import openai

        from service_model_manage.entity.chat_completion_entity import (
            ChatCompletionRequestParams,
        )
        from service_model_manage.service.chat_completion_service import OpenAILLMService

        openAILLMService = OpenAILLMService()
        openAILLMService.llm_model_client = openai.Client(api_key="not empty", base_url="http://10.8.21.166:9997/v1")
        openAILLMService.async_llm_model_client = openai.AsyncClient(
            api_key="not empty", base_url="http://10.8.21.166:9997/v1"
        )

        prompt = """Respond to the human as helpfully and accurately as possible. 

            {{instruction}}

            You have access to the following tools:

            {{tools}}

            Use a json blob to specify a tool by providing an action key (tool name) and an action_input key (tool input).
            Valid "action" values: "Final Answer" or {{tool_names}}

            Provide only ONE action per $JSON_BLOB, as shown:

            ```
            {
              "action": $TOOL_NAME,
              "action_input": $ACTION_INPUT
            }
            ```

            Follow this format:

            Question: input question to answer
            Thought: consider previous and subsequent steps
            Action:
            ```
            $JSON_BLOB
            ```
            Observation: action result
            ... (repeat Thought/Action/Observation N times)
            Thought: I know what to respond
            Action:
            ```
            {
              "action": "Final Answer",
              "action_input": "Final response to human"
            }
            ```

           Begin! Reminder to ALWAYS respond with a valid json blob of a single action. Use tools if necessary. Respond directly if appropriate. Format is Action:```$JSON_BLOB```then Observation:.
            {{historic_messages}}
            Question: {{query}}
            {{agent_scratchpad}}
            Thought:

            """
        historic_messages = ""
        agent_scratchpad = ""
        observation = """Observation: {{observation}}
            Question: {{query}}
            Thought:"""
        prompt = prompt.replace("{tools}", str(tool_list))
        prompt = prompt.replace("{instruction}", str(system_prompt))
        observation = observation.replace("{query}", str(query))
        prompt = prompt.replace("{query}", str(query))
        iteration = 0
        max_iteration = 3
        while iteration < max_iteration:
            iteration += 1
            # if historic_messages != "":
            #     prompt = prompt.replace("{historic_messages}", str({"historic_messages": historic_messages}))
            # if agent_scratchpad != "":
            #     prompt = prompt.replace("{agent_scratchpad}", str({"agent_scratchpad": agent_scratchpad}))
            response = openAILLMService.chunk_chat(
                request=ChatCompletionRequestParams(
                    model_uid="DeepSeek-R1-Distill-Qwen-32B", question=query, system_prompts=prompt
                )
            )
            match = re.search(r"```(.*?)```", response, re.DOTALL)
            if match:
                matched_str = match.group(1).strip()  # 获取匹配到的字符串并去除首尾空白字符
                # 将字符串转换为字典
                data = json.loads(matched_str)
                historic_messages = str(data)

            if data["action"] == "Final Answer":
                correct_result = data["action_input"]
                break
            for tool in tool_list:
                if data["action"] == tool["tool_name"]:
                    tool_url = tool["tool_url"]
                    params = data["action_input"]
                    import httpx

                    async with httpx.AsyncClient() as client:
                        response = await client.post(tool_url, json=params)
                    result = response.json()
            observation = observation.replace("{observation}", str(result))
            response_observation = openAILLMService.chunk_chat(
                request=ChatCompletionRequestParams(model_uid="qwen2-72B", question=query, system_prompts=observation)
            )
            correct_result = response_observation
            if iteration == max_iteration - 1:
                correct_result = result
                break
            agent_scratchpad = response_observation

    @staticmethod
    async def query_team_agent(agent_name, page, page_size, account_id, team_code_list, code, id, db, status=None):
        try:
            from datetime import datetime

            result = []
            final_results = []

            def parse_upload_time(upload_time_str):
                return datetime.strptime(upload_time_str, "%Y-%m-%d %H:%M:%S")

            status_condition = {}
            if status is not None:
                status_condition = {"status": status}

            if code != "":
                try:
                    if id != "":
                        condition = {
                            "$or": [
                                {"agent_name": {"$regex": rf"{re.escape(agent_name)}(\_.*)?", "$options": "i"}},
                                {"description": {"$regex": rf"{re.escape(agent_name)}(\_.*)?", "$options": "i"}},
                            ],
                            "code": code,
                            "_id": ObjectId(id),
                            "team_code": {"$in": team_code_list},
                        }
                    else:
                        condition = {
                            "$or": [
                                {"agent_name": {"$regex": rf"{re.escape(agent_name)}(\_.*)?", "$options": "i"}},
                                {"description": {"$regex": rf"{re.escape(agent_name)}(\_.*)?", "$options": "i"}},
                            ],
                            "code": code,
                            "team_code": {"$in": team_code_list},
                        }
                except:
                    return {"total": 0, "result": []}
                if status_condition:
                    condition["status"] = status
                results = MongodbUtil.query_docs_by_condition_pagination(
                    CollectionConfig.AGENT_COLLECTION,
                    search_condition=condition,
                    page=page,
                    page_size=page_size,
                    sort_field="create_time",
                    reverse=True,
                )
                for doc in results:
                    final_results.append(doc)
                len_result = MongodbUtil.count_documents_by_condition(CollectionConfig.AGENT_COLLECTION, condition)
            else:
                try:
                    if id != "":
                        condition = {
                            "$or": [
                                {"agent_name": {"$regex": rf"{re.escape(agent_name)}(\_.*)?", "$options": "i"}},
                                {"description": {"$regex": rf"{re.escape(agent_name)}(\_.*)?", "$options": "i"}},
                            ],
                            "_id": ObjectId(id),
                            "team_code": {"$in": team_code_list},
                        }
                    else:
                        condition = {
                            "$or": [
                                {"agent_name": {"$regex": rf"{re.escape(agent_name)}(\_.*)?", "$options": "i"}},
                                {"description": {"$regex": rf"{re.escape(agent_name)}(\_.*)?", "$options": "i"}},
                            ],
                            "team_code": {"$in": team_code_list},
                        }
                except:
                    return {"total": 0, "result": []}
                if status_condition:
                    condition["status"] = status
                results = MongodbUtil.query_docs_by_condition_pagination(
                    CollectionConfig.AGENT_COLLECTION,
                    search_condition=condition,
                    page=page,
                    page_size=page_size,
                    sort_field="create_time",
                    reverse=True,
                )
                for doc in results:
                    final_results.append(doc)
                len_result = MongodbUtil.count_documents_by_condition(CollectionConfig.AGENT_COLLECTION, condition)

            for item in final_results:
                temp = item.get("code", "")

                # 查询是否发布为mcp
                is_mcp_tool = False
                mcp_instance = MongodbUtil.query_docs_by_condition(
                    CollectionConfig.INSIDE_MCP_CONFIG, search_condition={"mcp_id": item["_id"]}
                )
                for item in mcp_instance:
                    is_mcp_tool = item.get("is_mcp_tool", False)

                result.append(
                    {
                        "agent_id": str(item["_id"]),
                        "agent_name": item["agent_name"],
                        "description": item["description"],
                        "account_id": item["account_id"],
                        "team_code": item["team_code"],
                        "status": item["status"],
                        "code": temp,
                        "is_mcp_tool": is_mcp_tool,
                    }
                )
            return {"total": len_result, "result": result}
        except Exception as e:
            raise e

    @staticmethod
    async def create_team_agent(agent_name, desripition, account_id, team_code, type_name, code, db):
        try:
            # usr_data = db.query(Team_Model).filter(Team_Model.status == 1,
            #                                        Team_Model.team_code == team_code).first()
            agent_id = ""
            create_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if code == "":
                code = "0"
                type_name = "其他"
            insert_result = MongodbUtil.insert_one(
                CollectionConfig.AGENT_COLLECTION,
                {
                    "agent_name": agent_name,
                    "description": desripition,
                    "create_time": create_time,
                    "account_id": account_id,
                    "team_code": team_code,
                    "type_name": type_name,
                    "code": code,
                    "status": 0,
                },
            )
            if insert_result is not None:
                agent_id = str(insert_result.inserted_id)
                model_info = await AgentService.running_LLM_model()
                model_info = (
                    model_info[0]
                    if len(model_info) != 0
                    else {"model_name": "", "id": "", "model_uid": "", "is_external": "", "max_tokens": 0}
                )
                model_params = {
                    "id": model_info["id"],
                    "model_uid": model_info["model_uid"],
                    "model_name": model_info["model_name"],
                    "max_token_length": model_info["max_tokens"],
                    "temperature": 0.8,
                    "history": 3,
                    "presence_penalty": 0,
                    "frequency_penalty": 0,
                }
                prompt = ""
                promptHtml = ""
                recall_setting = {
                    "is_rerank": False,
                    "rerank_id": None,
                    "rerank_model": "",
                    "rerank_name": "",
                    "top_k": 1,
                    "score": 0.8,
                }
                kb_list = list([])
                tool_list = list([])
                variable_list = list([])
                await AgentService.arrange_agent(
                    agent_id=agent_id,
                    account_id=account_id,
                    model_params=model_params,
                    prompt=prompt,
                    recall_setting=recall_setting,
                    kb_list=kb_list,
                    tool_list=tool_list,
                    variable_list=variable_list,
                    promptHtml=promptHtml,
                    prompt_id="",
                    is_question_rewriting=False,
                )
            return "新增智能体成功", agent_id

        except Exception:
            raise

    @staticmethod
    async def update_team_agent(agent_id, agent_name, description, team_code, db, code):
        try:
            # usr_data = db.query(Team_Model).filter(Team_Model.status == 1,
            #                                        Team_Model.team_code == team_code).first()
            # team_id = usr_data.id
            result = MongodbUtil.query_docs_by_condition(
                CollectionConfig.AGENT_COLLECTION, search_condition={"_id": ObjectId(agent_id)}
            )
            logger.info(f"查询智能体搜索结果: {result}")
            for item in result:
                MongodbUtil.update_one(
                    CollectionConfig.AGENT_COLLECTION,
                    query_filter={"_id": ObjectId(agent_id)},
                    update_operation={
                        "$set": {
                            "agent_name": agent_name,
                            "description": description,
                            "team_code": team_code,
                            "code": code,
                        }
                    },
                )
            return "更新智能体基础信息成功"

        except Exception as e:
            return False

    @staticmethod
    async def user_team_permission(account_id, team_code_list, db):
        team_id = []
        for i in range(len(team_code_list)):
            result = (
                db.query(Team_Model).filter(Team_Model.status == 1, Team_Model.team_code == team_code_list[i]).first()
            )
            team_id.append(result.id)
        for i in range(len(team_id)):
            result = (
                db.query(TeamMem_Model.team_id)
                .filter(
                    TeamMem_Model.account_id == account_id,
                    TeamMem_Model.status == 1,
                    TeamMem_Model.team_id == team_id[i],
                )
                .first()
            )
            if result != None:
                return True
            else:
                if i == len(team_id):
                    return False
                else:
                    continue

    @staticmethod
    async def verify_user_team_permission(account_id: str, team_code: str, db) -> bool:
        """
        验证用户是否属于指定团队

        Args:
            account_id: 用户账号ID
            team_code: 团队代码
            db: 数据库会话

        Returns:
            bool: 用户是否属于该团队
        """
        try:
            # 查询团队信息
            team = db.query(Team_Model).filter(Team_Model.status == 1, Team_Model.team_code == team_code).first()

            if not team:
                logger.info(f"团队不存在或已禁用: team_code={team_code}")
                return False

            # 查询用户是否为团队成员
            team_member = (
                db.query(TeamMem_Model)
                .filter(
                    TeamMem_Model.account_id == account_id, TeamMem_Model.status == 1, TeamMem_Model.team_id == team.id
                )
                .first()
            )

            return team_member is not None

        except Exception as e:
            return False

    @staticmethod
    async def get_agent_by_id(agent_id: str):
        """
        根据智能体ID获取智能体信息

        Args:
            agent_id: 智能体ID

        Returns:
            dict: 智能体信息，如果不存在返回None
        """
        try:
            result = MongodbUtil.query_docs_by_condition(
                CollectionConfig.AGENT_COLLECTION, search_condition={"_id": ObjectId(agent_id)}
            )

            for agent in result:
                return agent

            return None

        except Exception as e:
            return None

    @staticmethod
    async def verify_agent_permission(account_id: str, agent_id: str, db) -> tuple[bool, dict]:
        """
        验证用户是否有权限操作指定智能体

        Args:
            account_id: 用户账号ID
            agent_id: 智能体ID
            db: 数据库会话

        Returns:
            tuple[bool, dict]: (是否有权限, 智能体信息)
        """
        try:
            # 获取智能体信息
            agent = await AgentService.get_agent_by_id(agent_id)
            if not agent:
                logger.info(f"智能体不存在: agent_id={agent_id}")
                return False, None

            # 检查是否为个人智能体
            team_code = agent.get("team_code")
            if not team_code or team_code == "":
                # 个人智能体，检查是否为创建者
                if agent.get("account_id") == account_id:
                    return True, agent
                else:
                    logger.info(
                        f"用户无权限操作个人智能体: account_id={account_id}, agent_id={agent_id}, owner={agent.get('account_id')}"
                    )
                    return False, agent

            # 团队智能体，检查用户是否为团队成员
            has_permission = await AgentService.verify_user_team_permission(account_id, team_code, db)
            if not has_permission:
                logger.info(
                    f"用户无权限操作团队智能体: account_id={account_id}, agent_id={agent_id}, team_code={team_code}"
                )

            return has_permission, agent

        except Exception as e:
            return False, None

    @staticmethod
    async def update_agent_status(agent_id, status):
        try:
            result = MongodbUtil.query_docs_by_condition(
                CollectionConfig.AGENT_COLLECTION, search_condition={"_id": ObjectId(agent_id)}
            )
            logger.info(f"查询智能体搜索结果: {result}")
            for item in result:
                MongodbUtil.update_one(
                    CollectionConfig.AGENT_COLLECTION,
                    query_filter={"_id": ObjectId(agent_id)},
                    update_operation={
                        "$set": {
                            "status": status,
                        }
                    },
                )
            return "更新智能体基础信息成功"

        except Exception as e:
            return False

    @staticmethod
    async def create_type(code, name, description, account_name, usr_name):
        try:
            create_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            insert_result = MongodbUtil.insert_one(
                CollectionConfig.SYS_STATIC_DICT_TYPE,
                {
                    "code": code,
                    "name": name,
                    "cn_spell": "",
                    "scope_type": "",
                    "description": description,
                    "creator": account_name,
                    "creator_name": usr_name,
                    "create_time": create_time,
                    "modified_time": create_time,
                    "status": "1",
                    "updator": "",
                    "updator_name": "",
                },
            )
            if insert_result is not None:
                insert_result = str(insert_result.inserted_id)
            return "新增类别成功", insert_result

        except Exception as e:
            raise

    @staticmethod
    async def update_type(params, account_name, usr_name):
        try:
            updata_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            result = MongodbUtil.query_docs_by_condition(
                CollectionConfig.SYS_STATIC_DICT_TYPE, search_condition={"_id": ObjectId(params.id)}
            )
            for item in result:
                subcode = item["code"]

            tt = MongodbUtil.update_one(
                CollectionConfig.SYS_STATIC_DICT_TYPE,
                {"_id": ObjectId(params.id)},
                update_operation={
                    "$set": {
                        "name": params.name,
                        "code": params.code,
                        "description": params.description,
                        "updator": account_name,
                        "updator_name": usr_name,
                        "modified_time": updata_time,
                        "status": params.status,
                    }
                },
            )
            # 联表修改
            MongodbUtil.update_many(
                CollectionConfig.SYS_STATIC_DICT_ITEMS,
                {"type_code": subcode},
                update_operation={
                    "$set": {
                        "type_code": params.code,
                        "updator": account_name,
                        "updator_name": usr_name,
                        "modified_time": updata_time,
                    }
                },
            )

            return "更新类别信息成功"

        except Exception as e:
            raise

    @staticmethod
    async def delete_type(id):
        try:
            result = MongodbUtil.query_docs_by_condition(
                CollectionConfig.SYS_STATIC_DICT_TYPE, search_condition={"_id": ObjectId(id)}
            )
            for _ in result:
                MongodbUtil.update_one(
                    CollectionConfig.SYS_STATIC_DICT_TYPE,
                    {"_id": ObjectId(id)},
                    update_operation={"$set": {"status": "0"}},
                )
                return "删除类别信息成功"
        except Exception as e:
            raise

    @staticmethod
    async def query_type(name, code, status, page, page_size):
        try:
            from datetime import datetime

            condition = {
                "name": {"$regex": f"{re.escape(name)}(\\_.*)?", "$options": "i"},
                "code": {"$regex": f"{re.escape(code)}(\\_.*)?", "$options": "i"},
                "status": status,
            }
            result = []
            results = MongodbUtil.query_docs_by_condition(
                CollectionConfig.SYS_STATIC_DICT_TYPE, search_condition=condition
            )
            for item in results:
                result.append(
                    {
                        "id": str(item["_id"]),
                        "code": item["code"],
                        "name": item["name"],
                        "cn_spell": item["cn_spell"],
                        "scope_type": item["scope_type"],
                        "description": item["description"],
                        "creator": item["creator"],
                        "creator_name": item["creator_name"],
                        "create_time": item["create_time"],
                        "modified_time": item["modified_time"],
                        "status": item["status"],
                        "updator": item["updator"],
                        "updator_name": item["updator_name"],
                    }
                )

            def parse_upload_time(upload_time_str):
                return datetime.strptime(upload_time_str, "%Y-%m-%d %H:%M:%S")

            result = PageUtil.paginate_list(result, page, page_size)
            items = result["result"]
            results = sorted(items, key=lambda x: parse_upload_time(x["create_time"]), reverse=True)
            result["result"] = results
            return result
        except Exception as e:
            raise

    @staticmethod
    async def type_item_exist(code, type_code):
        try:
            condition = {"code": code, "type_code": type_code}
            results = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.SYS_STATIC_DICT_ITEMS, search_condition=condition
            )
            for _ in results:
                return True
            return False
        except Exception as e:
            raise

    @staticmethod
    async def create_item_type(code, type_code, name, description, account_name, usr_name):
        try:
            condition = {"type_code": type_code}
            results = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.SYS_STATIC_DICT_ITEMS, search_condition=condition
            )
            i = 0
            for item in results:
                i = i + 1

            create_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            insert_result = MongodbUtil.insert_one(
                CollectionConfig.SYS_STATIC_DICT_ITEMS,
                {
                    "code": code,
                    "type_code": type_code,
                    "name": name,
                    "description": description,
                    "creator": account_name,
                    "creator_name": usr_name,
                    "create_time": create_time,
                    "modified_time": create_time,
                    "status": "1",
                    "sort_no": i,
                    "updator": "",
                    "updator_name": "",
                },
            )
            if insert_result is not None:
                insert_result = str(insert_result.inserted_id)
            return "新增类别成功", insert_result

        except Exception as e:
            raise

    @staticmethod
    async def updata_item_type(params, account_name, usr_name):
        try:
            updata_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            MongodbUtil.update_one(
                CollectionConfig.SYS_STATIC_DICT_ITEMS,
                {"_id": ObjectId(params.id)},
                update_operation={
                    "$set": {
                        "name": params.name,
                        "description": params.description,
                        "code": params.code,
                        "updator": account_name,
                        "updator_name": usr_name,
                        "modified_time": updata_time,
                        "status": params.status,
                    }
                },
            )

            return "更新类别信息成功"

        except Exception as e:
            raise

    @staticmethod
    async def delete_item_type(id):
        try:
            result = MongodbUtil.query_docs_by_condition(
                CollectionConfig.SYS_STATIC_DICT_ITEMS, search_condition={"_id": ObjectId(id)}
            )
            for _ in result:
                MongodbUtil.update_one(
                    CollectionConfig.SYS_STATIC_DICT_ITEMS,
                    {"_id": ObjectId(id)},
                    update_operation={"$set": {"status": "0"}},
                )
                return "删除子类别信息成功"
        except Exception as e:
            raise

    @staticmethod
    async def query_item_type(name, code, status, page, page_size, type_code):
        try:
            condition = {
                "name": {"$regex": f"{re.escape(name)}(\\_.*)?", "$options": "i"},
                "code": {"$regex": f"{re.escape(code)}(\\_.*)?", "$options": "i"},
                "type_code": {"$regex": f"{re.escape(type_code)}(\\_.*)?", "$options": "i"},
                "status": status,
            }
            result = []
            results = MongodbUtil.query_docs_by_condition_pagination(
                CollectionConfig.SYS_STATIC_DICT_ITEMS,
                search_condition=condition,
                page=page,
                page_size=page_size,
                sort_field="create_time",
                reverse=True,
            )
            for item in results:
                result.append(
                    {
                        "id": str(item["_id"]),
                        "code": item["code"],
                        "type_code": item["type_code"],
                        "name": item["name"],
                        "status": item["status"],
                        "sort_no": item["sort_no"],
                        "description": item["description"],
                        "create_time": item["create_time"],
                    }
                )

            len_result = MongodbUtil.count_documents_by_condition(CollectionConfig.SYS_STATIC_DICT_ITEMS, condition)
            return {"total": len_result, "result": result}
        except Exception as e:
            raise e

    @staticmethod
    async def knowledge_whole_export(id, temp_id):
        try:
            # 知识库是否存在
            condition = {"_id": ObjectId(id)}
            is_exist = await KnowledgeService.is_knowledge_exist(condition)
            if not is_exist:
                raise HTTPException(detail="知识库不存在", status_code=400)

            # 存储待导出的知识库id，即老知识库id
            output_json = {"origin_knowledge_id": id}

            # 存储知识库表基本信息
            knowledge_arrange_info = MongodbUtil.query_doc_by_id(CollectionConfig.KB_ARRANGE_INFO, doc_id=ObjectId(id))
            knowledge_arrange_info.pop("_id", None)
            knowledge_info = MongodbUtil.query_doc_by_id(CollectionConfig.KB_COLLECTION, doc_id=ObjectId(id))
            logger.info(f"获取到的知识库基本信息成功，知识库基本信息为：{knowledge_info}")
            knowledge_info.pop("_id", None)
            output_json["knowledge_info"] = knowledge_info
            output_json["knowledge_arrange_info"] = knowledge_arrange_info

            # 再导出知识库上传文件基本信息
            upload_file_list = []
            file_parse_result_list = []
            parent_chunk_list = []
            upload_file_info_list = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION, search_condition={"knowledge_id": id}
            )
            for file in list(upload_file_info_list):
                upload_file_list.append(file)
                file_id = file["_id"]
                file_parse_result = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.FILE_PARSE_RESULT, doc_id=file_id
                )
                file_parse_result_list.append(file_parse_result)
                parent_chunk_result = MongodbUtil.query_docs_by_condition(
                    collection_name=CollectionConfig.CHUNK_COLLECTION, search_condition={"file_id": file_id}
                )
                for parent_chunk in parent_chunk_result:
                    parent_chunk.pop("_id", None)
                    parent_chunk_list.append(parent_chunk)

            logger.info(f"获取到的知识库上传文件基本信息成功，上传文件信息总数为：{len(upload_file_list)}")
            if not upload_file_list:
                logger.info("获取到的知识库上传文件为空")
            # 存储文件上传表信息
            output_json["upload_file_list"] = upload_file_list
            output_json["file_parse_result_list"] = file_parse_result_list
            output_json["parent_chunk_list"] = parent_chunk_list

            # 再获取向量数据库切片内容
            chunk_data_list = []
            if upload_file_list:
                create_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                milvus_connection = MilvusUtil("default")
                iterator = await milvus_connection.iterator_collection(batch_size=100, collection_name=f"_{id}")

                while True:
                    result = iterator.next()
                    if not result:
                        iterator.close()
                        break
                    for chunk_data in result:
                        chunk_data.pop("index", None)
                        chunk_data["create_time"] = create_time
                        try:
                            chunk_data["dense_vector"] = ast.literal_eval(chunk_data["dense_vector"])
                        except:
                            pass
                        for i in range(len(chunk_data["dense_vector"])):
                            chunk_data["dense_vector"][i] = float(chunk_data["dense_vector"][i])  # 转换数据类型
                        chunk_data_list.append(chunk_data)
                chunk_data_list = sorted(chunk_data_list, key=lambda x: (x["file_name"], x["number"]))
                logger.info(f"获取到{id}向量数据库切片内容成功,向量知识库切片总数为{len(chunk_data_list)}")

                # 使用完则关闭连接
                await milvus_connection.close()
            else:
                logger.info(f"不获取{id}向量数据库切片内容,其上传文件为空,向量知识库不存在")
            # 存储向量数据库信息
            if not chunk_data_list:
                logger.info("获取到的向量数据库数据为空")
            output_json["chunk_data_list"] = chunk_data_list

            local_folder = Path(__file__).parents[2] / "upload" / temp_id / id
            os.makedirs(local_folder, exist_ok=True)

            # 最后获取minio远程文件并压缩
            await KnowledgeService.download_minio_folder(
                bucket_name=MinioConfig.BUCKET_NAME, prefix=f"{id}/", local_folder=str(local_folder)
            )

            return output_json

        except HTTPException as he:
            raise he

        except Exception as e:
            raise HTTPException(status_code=400, detail="知识库整体导出失败")

    @staticmethod
    async def query_info_by_model_info(model_info):
        _id = ""
        model_name = ""
        try:
            model_info["is_delete"] = False
            query_result = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.MODEL_RUN_COLLECTION, search_condition=model_info
            )
            for item in query_result:
                _id = str(item["_id"])
                if item["is_external"]:
                    model_name = item["model_name"]
                else:
                    model_name = item["model_uid"]
                break
            return _id, model_name

        except Exception as e:
            return "", ""

    @staticmethod
    async def knowledge_whole_import(result, account_id, team_code, temp_id):
        try:
            temp_folder = Path(__file__).parents[2] / "upload" / "temp_import" / temp_id

            # 存储知识库不同部分导入的情况，当某一个部分导入成功时，记录成功信息。便于当知识库导入过程中因为某些原因失败时能够及时回溯
            import_check_info = {}

            # 导入知识库信息
            knowledge_info = result["json_content"]["knowledge_info"]
            from_kb = result["json_content"]["origin_knowledge_id"]
            knowledge_info["from_kb"] = from_kb
            knowledge_info.pop("_id", None)
            knowledge_info["kb_name"] += "_导入"
            knowledge_info["team_code"] = team_code
            knowledge_info["account_id"] = account_id

            def generate_node_id() -> str:
                return str(uuid.uuid4())

            # 替换嵌入模型_id
            model_info = {"model_uid": knowledge_info["embedding_model"]}
            _id, model_name = await AgentService.query_info_by_model_info(model_info)
            if _id and model_name:
                logger.info(f"导入知识库过程中查询到知识库嵌入模型信息：{_id}")
                knowledge_info["embedding_id"] = _id
            else:
                logger.info("导入知识库过程中未查询到嵌入模型信息")
            # 替换重排模型_id
            if knowledge_info["rerank_model"] and knowledge_info["rerank_id"]:
                model_info = {"model_uid": knowledge_info["rerank_model"]}
                _id, model_name = await AgentService.query_info_by_model_info(model_info)
                if _id and model_name:
                    knowledge_info["rerank_id"] = _id
                    knowledge_info["rerank_model"] = model_name
                    logger.info(f"导入知识库过程中查询到重排模型信息：{_id}")
                else:
                    knowledge_info["rerank_id"] = ""
                    knowledge_info["rerank_model"] = ""
                    logger.info("导入知识库过程中未查询到重排模型信息")
            insert_data = MongodbUtil.insert_one(
                collection_name=CollectionConfig.KB_COLLECTION, doc_content=knowledge_info
            )
            kb_id = str(insert_data.inserted_id)

            # 存储知识库导入id
            import_check_info["knowledge_import"] = {"status": True, "knowledge_id": kb_id}

            knowledge_arrange_info = result["json_content"].get("knowledge_arrange_info", None)
            if knowledge_arrange_info:
                knowledge_arrange_info["_id"] = ObjectId(kb_id)
                MongodbUtil.insert_one(
                    collection_name=CollectionConfig.KB_ARRANGE_INFO, doc_content=knowledge_arrange_info
                )

            # 建立minio远程文件路径与文件名称关联字典
            remote_path_dict = {}
            for file in range(len(result["files"])):
                result["files"][file] = result["files"][file].replace("\\", "/")
            minio_file_list = result["files"]
            for minio_file in minio_file_list:
                remote_file_name = os.path.basename(minio_file)
                remote_path_dict[remote_file_name] = minio_file

            # 导入上传文件基本信息与上传文件至minio文件服务器
            import_check_info["file_import"] = []
            origin_knowledge_id = result["json_content"]["origin_knowledge_id"]
            file_id_dict = {}
            upload_file_list = result["json_content"]["upload_file_list"]
            file_parse_result_list = result["json_content"]["file_parse_result_list"]
            parent_chunk_list = result["json_content"]["parent_chunk_list"]
            other_file_list = result["files"]
            for upload_file in upload_file_list:
                if upload_file.get("pdf_path", ""):
                    upload_file["pdf_path"] = upload_file["pdf_path"].replace(str(origin_knowledge_id), str(kb_id))
                if upload_file.get("convert_path", ""):
                    upload_file["convert_path"] = upload_file["convert_path"].replace(
                        str(origin_knowledge_id), str(kb_id)
                    )
                if upload_file.get("layout_path", ""):
                    upload_file["layout_path"] = upload_file["layout_path"].replace(
                        str(origin_knowledge_id), str(kb_id)
                    )
                if upload_file.get("account_id", ""):
                    upload_file["account_id"] = account_id
                remote_path = f"{kb_id}/{upload_file['file_name']}"
                _id = generate_unique_id("F", datacenter_id=1, worker_id=1)
                await asyncio.sleep(0.1)
                create_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                file_id_dict[upload_file["_id"]] = _id
                upload_file["_id"] = _id
                upload_file["knowledge_id"] = kb_id
                upload_file["create_time"] = create_time
                try:
                    await run_in_threadpool(
                        MinIoUtil.upload_file,
                        "tiance-base",
                        remote_path,
                        temp_folder / remote_path_dict[upload_file["file_name"]],
                    )
                    other_file_list.remove(upload_file["remote_path"])
                    upload_file["remote_path"] = remote_path
                except Exception as e:
                    logger.info(f"远程文件上传失败，失败原因：<{traceback.format_exc()}>")
                    upload_file["remote_path"] = ""
                insert_file = MongodbUtil.insert_one(
                    collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION, doc_content=upload_file
                )
                file_id = str(insert_file.inserted_id)

                # 存储文件信息id
                import_check_info["file_import"].append({"status": True, "file_id": file_id})
            for file_parse_result in file_parse_result_list:
                if file_parse_result and file_id_dict.get(file_parse_result["_id"], None):
                    file_parse_result["_id"] = file_id_dict[file_parse_result["_id"]]
                    for index in range(len(file_parse_result["parse_result"]["result"])):
                        if file_parse_result["parse_result"]["result"][index].get("img_path", None):
                            file_parse_result["parse_result"]["result"][index]["img_path"] = file_parse_result[
                                "parse_result"
                            ]["result"][index]["img_path"].replace(str(origin_knowledge_id), str(kb_id))
                    MongodbUtil.insert_one(
                        collection_name=CollectionConfig.FILE_PARSE_RESULT, doc_content=file_parse_result
                    )
            # 导入其他文件至文件服务器
            for other_file in other_file_list:
                try:
                    remote_path = other_file.replace(origin_knowledge_id, kb_id)
                    remote_path = remote_path.replace("\\", "/")
                    await run_in_threadpool(MinIoUtil.upload_file, "tiance-base", remote_path, temp_folder / other_file)
                except Exception as e:
                    logger.info(f"远程文件上传失败，失败原因：<{traceback.format_exc()}>")

            # 导入向量知识库切块内容
            milvus_connection = MilvusUtil("default")
            milvus_id = f"_{kb_id}"
            milvus = MilvusUtil()
            supports_sparse_vector = knowledge_info.get("supports_sparse_vector", False)
            await milvus.create_hybrid_collection(
                collection_name=milvus_id,
                dense_dim=knowledge_info["embedding_dimension"],  # 修正参数名称
                enable_bm25=True,  # 支持BM25全文检索
                enable_model_sparse=supports_sparse_vector,  # 根据模型实际支持情况决定是否启用稀疏向量
            )
            chunk_data_list = result["json_content"]["chunk_data_list"]
            chunk_data_list = sorted(chunk_data_list, key=lambda x: (x["file_name"], x["number"]))
            child_chunk_dict = {}
            parent_chunk_dict = {}
            for parent_chunk in parent_chunk_list:
                parent_id = generate_node_id()
                parent_chunk_dict[parent_chunk["chunk_id"]] = parent_id
                parent_chunk["chunk_id"] = parent_id
                parent_node = []
                for child_chunk_id in parent_chunk["parent_node"]:
                    child_id = generate_node_id()
                    child_chunk_dict[child_chunk_id] = child_id
                    parent_node.append(child_id)
                parent_chunk["parent_node"] = parent_node
                parent_chunk["knowledge_id"] = kb_id
                parent_chunk["file_id"] = file_id_dict[parent_chunk["file_id"]]
                MongodbUtil.insert_one(collection_name=CollectionConfig.CHUNK_COLLECTION, doc_content=parent_chunk)
            for chunk_data in chunk_data_list:
                create_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                chunk_data["file_time"] = create_time
                chunk_data["file_id"] = file_id_dict[chunk_data["file_id"]]
                if chunk_data["chunk_split_type"] != "tradition":
                    chunk_data["chunk_id"] = child_chunk_dict[chunk_data["chunk_id"]]
                    chunk_data["parent_node"] = [parent_chunk_dict[item_id] for item_id in chunk_data["parent_node"]]
                if chunk_data.get("source_data", None):
                    for source_data in chunk_data["source_data"]:
                        if source_data.get("images_urls", None):
                            for image_url_index in range(len(source_data["images_urls"])):
                                source_data["images_urls"][image_url_index] = source_data["images_urls"][
                                    image_url_index
                                ].replace(str(origin_knowledge_id), str(kb_id))
                if chunk_data.get("create_time", None):
                    chunk_data["create_time"] = create_time

            batch_size = 100  # 每批次插入的数据量
            for i in range(0, len(chunk_data_list), batch_size):
                batch_data = chunk_data_list[i : i + batch_size]
                await milvus.add_document(collection_name=f"_{kb_id}", data=batch_data)

            return kb_id, knowledge_info["kb_name"]

        except Exception as e:
            detail = f"获取指定知识库文件数与处理结果数失败：《{e}》"
            logger.info(f"获取指定知识库文件数与处理结果数失败，失败原因：{str(traceback.format_exc())}")

            # 如果知识库导入失败，删除本次上传保存的所有信息
            # 先获取知识库id，根据知识库id可以删除知识库基本信息表、minio上传文件、向量数据库数据。如果知识库id不存在，说明最开始的插入知识库基本信息表未完成，后续操作则都未完成，直接跳过即可
            if import_check_info.get("knowledge_import"):
                knowledge_id = import_check_info["knowledge_import"]["knowledge_id"]
                # 删除知识库信息
                MongodbUtil.del_doc_by_id(collection_name=CollectionConfig.KB_COLLECTION, doc_id=ObjectId(knowledge_id))
                logger.info(f"知识库基本信息表数据删除成功，知识库id为《《{knowledge_id}》》")
                # 删除minio文件夹
                folder_prefix = f"{knowledge_id}/"

                def delete_minio_files(folder_prefix):
                    objects = MinIoUtil.get_file_list(MinioConfig.BUCKET_NAME, prefix=folder_prefix)
                    logger.info(f"移除的远程文件名称列表为{objects}")
                    for obj in objects:
                        file_name = os.path.basename(obj)
                        if file_name:
                            MinIoUtil.delete_file(MinioConfig.BUCKET_NAME, obj)
                        else:
                            delete_minio_files(obj)

                delete_minio_files(folder_prefix)

                # 删除向量数据库
                milvus = MilvusUtil()
                await milvus.drop_collection(collection_name=f"_{knowledge_id}")

            # 删除上传文件信息表信息
            if import_check_info.get("file_import"):
                file_info_list = import_check_info["file_import"]
                for file_info in file_info_list:
                    MongodbUtil.del_doc_by_id(
                        collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION, doc_id=file_info["file_id"]
                    )
                    logger.info(f"文件上传基本信息表数据删除成功，文件id为《《{file_info['file_id']}》》")

            raise

    @staticmethod
    async def list_knowledge(account_id: str, team_codes: list):
        try:
            results = []
            if team_codes:
                result = MongodbUtil.query_docs_by_condition(
                    CollectionConfig.KB_COLLECTION, search_condition={"team_code": {"$in": team_codes}}
                )
            else:
                result = MongodbUtil.query_docs_by_condition(
                    CollectionConfig.KB_COLLECTION, search_condition={"account_id": account_id, "team_code": ""}
                )
            for item in result:
                item["_id"] = str(item["_id"])
                results.append(item)
            # return RetUtil.return_ok(result)
            return results
        except Exception as e:
            raise


##################################################################################以下方法为暂时不用##############################################################################################
# @staticmethod
# async def extract_content_after_think(response):
#     content = response[0]["content"]
#     return content
#
#
# @staticmethod
# async def list_tool():
#     try:
#         results = []
#         result = MongodbUtil.query_docs_by_condition(CollectionConfig.TOOL_COLLECTION, search_condition={})
#         for item in result:
#             tool_params = []
#             tool_name = item["tool_name"]
#             schema = item["schema"]
#             schema = json.loads(schema)
#             for path, path_item in schema.get("paths", {}).items():
#                 for method, operation in path_item.items():
#                     if "requestBody" in operation and "content" in operation["requestBody"]:
#                         for media_type, media_details in operation["requestBody"]["content"].items():
#                             schema1 = media_details.get("schema", {})
#                             properties = schema1.get("properties", {})
#                             for prop_name, prop_details in properties.items():
#                                 tool_params.append(prop_name)
#             logger.info(f"工具参数列表:{tool_params}，得到的schema:{str(schema)}")
#             server_url = schema["servers"][0]["url"]
#             api_path = next(iter(schema["paths"]))
#             api_url = server_url + api_path
#             results.append({"tool_name": item["tool_name"], "tool_params": tool_params, "tool_url": api_url})
#         # return RetUtil.return_ok(result)
#         return results
#     except Exception as e:
#         raise
#
# @staticmethod
# async def type_exist(code: str):
#     try:
#         condition = {"code": code}
#         agent = MongodbUtil.query_docs_by_condition(
#             collection_name=CollectionConfig.SYS_STATIC_DICT_TYPE, search_condition=condition
#         )
#         for _ in agent:
#             return True
#         return False
#     except Exception as e:
#         raise
