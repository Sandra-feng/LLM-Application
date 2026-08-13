import asyncio
import base64
from loguru import logger
import os
import traceback
from pathlib import Path

from fastapi.concurrency import run_in_threadpool

from base_utils.minio_util import MinIoUtil
from base_utils.mongodb_util import MongodbUtil
from service_agent_manage.service.agent_service import AgentService
from service_model_manage.service.chat_completion_service import OpenAILLMService
from service_usr_manage.service.snow_util import generate_unique_id
# logger = loguru logger (auto-migrated)
async def get_image_count(QUESTION):
    try:
        image_count = int(
            MongodbUtil.query_doc_by_id(collection_name="model_config", doc_id="model_config")["image_count"]
        )
        if image_count <= 0:
            image_count = 4
        elif image_count <= 10:
            image_count = image_count
        else:
            image_count = 10
        system_prompts = f'''
            你将接收到一段文本。请根据这段文本分析出用户需要生成的图片的数量，返回且仅返回这个数字。
    
            以下是你需要遵循的步骤：
            1. 直接输出结果，不要携带思考过程或额外文字。
            2. 如果文本中没有明确提到图片数量，输出默认值"{image_count}"。
            3. 仔细阅读并理解提供的文本内容。
            4. 如果用户直接输入数字，输出默认值"{image_count}"。
            5. 如果用户需要生成的图片数量大于"10"，最后结果直接输出"10"，不要携带分析过程，只要输出数字结果。
            
            文本片段:
            "QUESTION"
            
            输出结果：
            "NUMBER"
            
            示例：
            文本片段: "请根据这段描述生成一张图片：宁静的夏日午后，一只小猫在窗边打盹。"
            输出结果：
            "1"
            
            文本片段: "请生成五张哈士奇图片。"
            输出结果：
            "5"
            
            文本片段: "雨中的小女孩"
            输出结果：
            "{image_count}"
            
            文本片段: "1"
            输出结果：
            "{image_count}"
            
            文本片段: "2222"
            输出结果：
            "{image_count}"
            
            '''
        system_prompts = system_prompts.replace("QUESTION", QUESTION)

        id, model = await AgentService.get_first_running_model()  # 获取运行中的大模型
        openAILLMService = OpenAILLMService(id=id)

        completion = openAILLMService.llm_model_client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompts}],
            temperature=0.3,
            max_tokens=1024,
            stream=False,
        )

        number = completion.choices[0].message.content
        index = completion.choices[0].message.content.find("</think>")  # 推理模型过滤思考内容
        if index != -1:
            number = number[index + len("</think>") :]
            logger.info(f"推理模型过滤思考内容结果为{number}")

        try:
            number = int(number)
        except:
            number = 1

        return number

    except Exception as e:
        logger.error(f"获取用户提问的图片数量出错: {str(traceback.format_exc())}")
        number = 1
        return number


async def get_question(QUESTION):
    try:
        system_prompts = """
            你将接收到一段文本。请按照以下要求处理文本：
            1. 将文本翻译为英文。
            2. 从翻译后的文本中移除与图片数量相关的词语（如 "three images of"、"two pictures of" 等），但保留其他量词与文本内容。
            3. 输出结果只需是移除图片数量相关词语后的翻译文本，不要包含其他任何内容或解释。
            4. 输出结果不要包含任何中文与英文的内容解释，只需要输出最终结果。
            5. 如果接收的文本内容没有包含任何的信息与翻译价值，直接返回翻译后的文本内容，但是不要包含其他内容。
            
            文本片段：
            "{QUESTION}"
            
            输出结果：
            "{ENGLISH_DESCRIPTION}"
            
            示例：
            文本片段: "三张两只哈士奇比赛跑步的图片"
            输出结果：
            "image of two Huskies racing"
            
            文本片段: "两朵花争奇斗艳"
            输出结果：
            "Two flowers are competing in beauty and splendor"
            
            如果文本中没有提到图片数量或与图片无关，只需输出翻译后的文本内容，不要携带输出与结果过程的内容。
            
            示例：
            文本片段: "1234"
            输出结果：
            "One two three"
            
            文本片段: "大大消息"
            输出结果：
            "Very big News"
            
            """
        system_prompts = system_prompts.replace("{QUESTION}", QUESTION)

        id, model = await AgentService.get_first_running_model()  # 获取运行中的大模型
        openAILLMService = OpenAILLMService(id=id)

        completion = openAILLMService.llm_model_client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompts}],
            temperature=0.3,
            max_tokens=1024,
            stream=False,
        )

        result = completion.choices[0].message.content
        index = completion.choices[0].message.content.find("</think>")  # 推理模型过滤思考内容
        if index != -1:
            result = result[index + len("</think>") :]
            logger.info(f"推理模型过滤思考内容结果为{result}")

        return result

    except Exception as e:
        logger.error(f"获取用户提问的英文描述出错: {str(traceback.format_exc())}")
        return ""


async def image_save(response):
    local_paths = []
    remote_paths = []

    try:
        for image in response.data:
            b64_json = image.b64_json
            image_data = base64.b64decode(b64_json)

            # 保存图片到本地
            upload_path = Path(__file__).parents[3] / "upload" / "generated_images"
            if not os.path.exists(upload_path):
                os.makedirs(upload_path)

            image_id = generate_unique_id("IMAGE_", datacenter_id=1, worker_id=1)
            await asyncio.sleep(0.5)

            local_path = f"{upload_path}/{image_id}.png"
            with open(local_path, "wb") as image_file:
                image_file.write(image_data)
            local_paths.append(local_path)

            bucket_name = "tiance-base"
            remote_path = f"generated_images/{image_id}.png"
            await run_in_threadpool(MinIoUtil.upload_image_file, bucket_name, remote_path, local_path)
            remote_paths.append(remote_path)

        return local_paths, remote_paths

    except:
        detail = f"文生图图片保存失败：失败原因<{traceback.format_exc()}>"
        logger.error(msg=detail)
        return [], []


async def image_to_image_save(response):
    local_paths = []
    remote_paths = []

    try:
        for image in response["data"]:
            b64_json = image["b64_json"]
            image_data = base64.b64decode(b64_json)

            # 保存图片到本地
            upload_path = Path(__file__).parents[3] / "upload" / "generated_images"
            if not os.path.exists(upload_path):
                os.makedirs(upload_path)

            image_id = generate_unique_id("IMAGE_", datacenter_id=1, worker_id=1)
            await asyncio.sleep(0.5)

            local_path = f"{upload_path}/{image_id}.png"
            with open(local_path, "wb") as image_file:
                image_file.write(image_data)
            local_paths.append(local_path)

            bucket_name = "tiance-base"
            remote_path = f"generated_images/{image_id}.png"
            await run_in_threadpool(MinIoUtil.upload_image_file, bucket_name, remote_path, local_path)
            remote_paths.append(remote_path)

        return local_paths, remote_paths

    except:
        detail = f"图生图图片保存失败：失败原因<{traceback.format_exc()}>"
        logger.error(msg=detail)
        return [], []


async def save_img(image_data):
    try:
        upload_path = Path(__file__).parents[2] / "upload" / "generated_images"
        if not os.path.exists(upload_path):
            os.makedirs(upload_path)

        image_id = generate_unique_id("IMAGE_", datacenter_id=1, worker_id=1)
        await asyncio.sleep(0.5)

        local_path = f"{upload_path}/{image_id}.png"
        with open(local_path, "wb") as image_file:
            image_file.write(image_data)

        bucket_name = "tiance-base"
        remote_path = f"generated_images/{image_id}.png"
        await run_in_threadpool(MinIoUtil.upload_image_file, bucket_name, remote_path, local_path)
        remote_path = remote_path

        return local_path, remote_path

    except:
        detail = f"本地图片保存失败：失败原因<{traceback.format_exc()}>"
        logger.error(msg=detail)
        return "", ""


async def remote_image_data(remote_path):
    try:
        upload_path = Path(__file__).parents[2] / "upload" / "generated_images"
        if not os.path.exists(upload_path):
            os.makedirs(upload_path)

        image_id = generate_unique_id("IMAGE_", datacenter_id=1, worker_id=1)
        await asyncio.sleep(0.5)

        local_path = f"{upload_path}/{image_id}.png"
        MinIoUtil.download_file(bucket_name="tiance-base", remote_path=remote_path, local_path=local_path)

        with open(local_path, "rb") as image_file:
            image_data = image_file.read()

        import cv2
        import numpy as np

        image_array = cv2.imdecode(np.frombuffer(image_data, np.uint8), cv2.IMREAD_UNCHANGED)
        if image_array.shape[2] == 4:
            image_array = cv2.cvtColor(image_array, cv2.COLOR_RGBA2RGB)
            _, encoded_image = cv2.imencode(".png", image_array)
            image_data = encoded_image.tobytes()

        return image_data

    except:
        detail = f"下载远程文件：失败原因<{traceback.format_exc()}>"
        logger.error(msg=detail)
        return ""

    finally:
        if os.path.exists(local_path):
            os.remove(local_path)
