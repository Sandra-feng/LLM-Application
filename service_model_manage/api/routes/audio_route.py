import asyncio
import time
import traceback

from fastapi import APIRouter, WebSocket

from service_model_manage.service.audio_service import generate_audio_from_text, generate_txt_to_audio

from loguru import logger
# logger = loguru logger (auto-migrated)
router = APIRouter()

timeout = 5


# @router.websocket("/audio_to_txt")
# async def audio_to_txt(websocket: WebSocket):
#     last_ping_time = time.time()  # 记录连接时间
#     await websocket.accept()
#     # 持续接收音频数据直到用户结束会话
#     audio_list = []
#     while True:
#         try:
#             # 设定一个超时限制，定期检查是否过久未发送心跳
#             if time.time() - last_ping_time > 60.0:  # 60秒未发送心跳，关闭websocket
#                 await websocket.send_json(
#                     {
#                         "code": 500,
#                         "message": "ping timeout,websocket closed",
#                         "status": "False",
#                         "data": {
#                             "result": None,
#                             "spend_time": f"{(time.time() - last_ping_time):.2f}",
#                             "tokens_consume": 0,
#                         },
#                     }
#                 )
#                 await websocket.close()
#                 break
#             start_time = time.time()
#             data = await websocket.receive_json()
#             if data:
#                 model_uid = data.get("model_uid")
#                 index = data.get("index")
#                 is_last = data.get("is_last")
#                 if index == 0:
#                     audio_list = []
#                 if data.get("is_close", False) is True:
#                     await websocket.close()
#                     break
#                 if data.get("type") and data["type"] == "ping":
#                     last_ping_time = time.time()  # 记录连接时间
#                     continue
#                 # 接收音频文件的二进制数据
#                 audio_data = await websocket.receive_bytes()
#                 if audio_data:
#                     audio_list.append(audio_data)
#                     # 异步调用 OpenAI 接口进行语音识别
#                     recognized_json = await generate_audio_from_text(audio_data, model_uid, start_time, is_last)
#                     await websocket.send_json(recognized_json)
#                 if is_last:
#                     # print("is_last..")
#                     logger.info("is_lasting")
#                     # 合并音频（速度很慢）
#                     # # 加载第一个音频文件
#                     # bytes_audio = AudioSegment.from_file(io.BytesIO(audio_list[0]))
#                     #
#                     # # 合并其他音频文件
#                     # for file in audio_list[1:]:
#                     #     next_audio = AudioSegment.from_file(io.BytesIO(file))
#                     #     bytes_audio += next_audio  # 拼接音频
#                     #
#                     # output_stream = io.BytesIO()
#                     # bytes_audio.export(output_stream, format="wav")
#                     # # bytes_audio.export("C:/Users/L/PycharmProjects/tiance-base/test/zero_shot_example2.wav", format="wav")
#                     # # 异步调用 OpenAI 接口进行语音识别
#                     # recognized_json = await generate_audio_from_text(output_stream.getvalue(), model_uid, start_time,
#                     #                                                  is_last)
#                     # await websocket.send_json(recognized_json)
#
#         except asyncio.exceptions.TimeoutError:
#             await websocket.send_json(
#                 {
#                     "code": 500,
#                     "message": "Error: WebSocket Connection timed out.",
#                     "status": "False",
#                     "data": {
#                         "result": None,
#                         "spend_time": f"{(time.time() - last_ping_time):.2f}",
#                         "tokens_consume": 0,
#                     },
#                 }
#             )
#
#         except Exception as e:
#             await websocket.send_json(
#                 {
#                     "code": 500,
#                     "message": f"Error: {str(traceback.format_exc())}",
#                     "status": "False",
#                     "data": {
#                         "result": None,
#                         "spend_time": f"{(time.time() - last_ping_time):.2f}",
#                         "tokens_consume": 0,
#                     },
#                 }
#             )


# WebSocket 端点，接收文本并进行语音识别
# @router.websocket("/txt_to_audio")
# async def txt_to_audio(websocket: WebSocket):
#     last_ping_time = time.time()  # 记录连接时间
#     await websocket.accept()
#     # 持续接收音频数据直到用户结束会话
#     while True:
#         try:
#             # 设定一个超时限制，定期检查是否过久未发送心跳
#             if time.time() - last_ping_time > 60.0:  # 60秒未发送心跳，关闭websocket
#                 await websocket.send_json(
#                     {
#                         "code": 500,
#                         "message": "ping timeout,websocket closed",
#                         "status": "False",
#                         "data": {
#                             "result": None,
#                             "spend_time": f"{(time.time() - last_ping_time):.2f}",
#                             "tokens_consume": 0,
#                         },
#                     }
#                 )
#                 await websocket.close()
#                 break
#             start_time = time.time()  # 记录连接启动时间
#             # 接收客户端发送的文本和声音类型
#             data = await websocket.receive_json()  # 期望接收到JSON格式的数据
#             input_txt = data.get("input_txt")
#             voice_type = data.get("voice_type", "中文女")
#             model_uid = data.get("model_uid")
#             if data.get("is_close", False) is True:
#                 await websocket.close()
#                 break
#             if data.get("type") and data["type"] == "ping":
#                 last_ping_time = time.time()  # 记录连接时间
#                 continue
#             if not input_txt:
#                 await websocket.send_json(
#                     {
#                         "code": 500,
#                         "message": "Error: Missing text",
#                         "status": "False",
#                         "data": {
#                             "result": None,
#                             "spend_time": f"{(time.time() - start_time):.2f}",
#                             "tokens_consume": 0,
#                         },
#                     }
#                 )
#                 await websocket.close()
#             # 异步调用 OpenAI 接口进行语音识别
#             recognized_bytes = await generate_txt_to_audio(input_txt, voice_type, model_uid)
#             if type(recognized_bytes) is str and recognized_bytes.startswith("Error during transcription: "):
#                 await websocket.send_json(
#                     {
#                         "code": 500,
#                         "message": recognized_bytes,
#                         "status": "False",
#                         "data": {
#                             "result": None,
#                             "spend_time": f"{(time.time() - start_time):.2f}",
#                             "tokens_consume": 0,
#                         },
#                     }
#                 )
#                 await websocket.send_bytes(b"")
#             else:
#                 await websocket.send_json(
#                     {
#                         "code": 200,
#                         "message": "success",
#                         "status": "True",
#                         "data": {
#                             "spend_time": f"{(time.time() - start_time):.2f}",
#                             "tokens_consume": 123,
#                         },
#                     }
#                 )
#                 await websocket.send_bytes(recognized_bytes)
#         except asyncio.exceptions.TimeoutError:
#             await websocket.send_json(
#                 {
#                     "code": 500,
#                     "message": "Error: WebSocket Connection timed out.",
#                     "status": "False",
#                     "data": {
#                         "result": None,
#                         "spend_time": f"{(time.time() - last_ping_time):.2f}",
#                         "tokens_consume": 0,
#                     },
#                 }
#             )
#         except Exception as e:
#             await websocket.send_json(
#                 {
#                     "code": 500,
#                     "message": f"Error: {str(traceback.format_exc())}",
#                     "status": "False",
#                     "data": {
#                         "result": None,
#                         "spend_time": f"{(time.time() - last_ping_time):.2f}",
#                         "tokens_consume": 0,
#                     },
#                 }
#             )
