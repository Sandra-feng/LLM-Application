import io
import time
import traceback
import openai

from base_configs.model_config import ModelConfig

client = openai.Client(
    api_key=ModelConfig.AUDIO_API_KEY,
    base_url=ModelConfig.AUDIO_API_BASE
)


async def generate_audio_from_text(audio_data: bytes, model_uid: str, start_time: float, is_last: bool) -> dict:
    try:
        audio_file = io.BytesIO(audio_data)
        result = client.audio.transcriptions.create(
            model=model_uid,
            file=audio_file,
        )

        return {
            "code": 200,
            "message": "success",
            "status": 'True',
            "data": {
                "result": result.text,
                "spend_time": f"{(time.time() - start_time):.2f}",
                "tokens_consume": 123,
                "is_last": is_last
            }
        }
    except Exception as e:
        return {
            "code": 500,
            "message": str(e),
            "status": 'False',
            "data": {
                "result": None,
                "spend_time": f"{(time.time() - start_time):.2f}",
                "tokens_consume": 0,
                "is_last": is_last
            }
        }


async def generate_txt_to_audio(text: str, voice_type: str, model_uid: str):
    try:
        response = client.audio.speech.create(
            model=model_uid,
            input=text,
            # ['中文女', '中文男', '日语男', '粤语女', '英文女', '英文男', '韩语女']
            voice=voice_type
        )
        return response.read()
    except Exception as e:
        return f"Error during transcription: {str(e)}"
