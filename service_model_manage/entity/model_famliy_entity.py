
from service_model_manage.entity.common_type import ModelType
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Union
from base_utils.log_util import LogUtil
class ModelLlmDetailEntity(BaseModel):
    model_engine: List[str] = Field(..., examples=[["vLLM", "Transformers", "SGLang", "llama.cpp"]], description="模型引擎")
    model_format: List[str] = Field(..., examples=[["pytorch", "gptq", "awq","fp8"]], description="模型格式类别")
    model_size_in_billions: List[Union[str, int]] = Field(..., examples=[["0_5","1_8",7, 8,9,14,32,70,72,110]], description="模型大小")
    quantizations: List[str] = Field(..., examples=[["none", "Int4", "Int8"]], description="模型量化")
    model_contex_length:str = Field(..., examples=["128k"], description="模型上下文长度")

class ModelEmbDetailEntity(BaseModel):
    model_contex_length:Optional[int] = Field(..., examples=[512], description="最大输入长度")
    model_embedding_dimension: Optional[int] = Field(..., examples=[512], description="嵌入模型维度")

class ModelListEntity(BaseModel):
    model_id: str = Field(..., examples=["Qwen2"], description="模型ID")
    model_type: str = Field(..., examples=["LLM"], description="模型类型")
    model_description: Optional[str] = Field(None, examples=["A large language model developed by Alibaba Group"], description="模型描述")
    model_llm_details: Optional[ModelLlmDetailEntity] = Field(None, description="大模型详细信息")
    model_emb_details: Optional[ModelEmbDetailEntity] = Field(None, description="嵌入模型详细信息")



class ModelFamliyEntity(object):
    '''
    {
        '_id': ObjectId('66cd9351e4ba9349a4a54438'), 
        'model_id': 'llama', 
        'model_type': 'LLM', 
        'model_description': 'xxx', 
        'model_run_details': {
            'model_engine': ['vllm', 'transformers'], 
            'model_format': ['pytorch', 'gptq'], 
            'model_size_in_billions': ['7', '14'], 
            'quantazations': ['none', 'int4', 'int8']
        }, 
        'is_remove': 0
    }
    '''
    def __init__(self, model):
        # LogUtil.debug("get from db {0}".format(str(model)))
        self.model_id = model['model_id']
        self.model_type = model['model_type']

    
        self.model_description = model['model_description']

        self.model_run_details = {}
        if 'model_llm_details' in  model :
            self.model_run_details["model_engine"] = model["model_llm_details"]["model_engine"]
            self.model_run_details["model_format"] = model["model_llm_details"]["model_format"]
            if self.model_type != ModelType.LLM.value:
                self.model_run_details["model_size_in_billions"] = ""
                self.model_run_details["quantizations"] = ""
            else:
                self.model_run_details["model_size_in_billions"] = model["model_llm_details"]["model_size_in_billions"] 
                self.model_run_details["quantizations"] = model["model_llm_details"]["quantizations"]
        else:
            self.model_run_details = ""

    def to_dict(self):
        return {
            "model_id": self.model_id,
            "model_type": self.model_type, 
            "model_description": self.model_description, 
            "model_run_details": self.model_run_details
        }


class ModelFamliyListEntity(object):
 
    def __init__(self, model):
        self.model_id = model['model_id']
        self.model_type = model['model_type']
        self.model_description = model['model_description']
        self.model_llm_details = model['model_llm_details']
        self.model_emb_details = model['model_emb_details']
        
    def to_dict(self):
        if self.model_type == ModelType.LLM.value:
            return {"_id": self.model_id,"model_id": self.model_id, "model_type": self.model_type,
                                 "model_description": self.model_description, "model_llm_details": self.model_llm_details}
        if self.model_type == ModelType.EMBEDDIND.value:
            return {"_id": self.model_id,"model_id": self.model_id, "model_type": self.model_type,
                                 "model_description": self.model_description, "model_emb_details": self.model_emb_details}
        else:
            return {"_id": self.model_id,"model_id": self.model_id, "model_type": self.model_type,
                                 "model_description": self.model_description}
        
    def to_prompt_dict(self):
        if self.model_type == ModelType.LLM.value:
            return {"model_id": self.model_id, "model_type": self.model_type,
                                 "model_description": self.model_description, "model_llm_details": self.model_llm_details}
        if self.model_type == ModelType.EMBEDDIND.value:
            return {"model_id": self.model_id, "model_type": self.model_type,
                                 "model_description": self.model_description, "model_emb_details": self.model_emb_details}
        else:
            return {"model_id": self.model_id, "model_type": self.model_type,
                                 "model_description": self.model_description}

    def to_base_dict(self):
        """
        功能说明： 返回模型的基本信息字典   "model_id  ,"model_type" "modle_description"
        """
        return {
            "model_id": self.model_id,
            "model_type": self.model_type,
            "model_description": self.model_description
        }


class Model_List_Entity(object):
    """
    功能说明：返回模型列表实体
    返回的字典中涉及"is_remove"，用于表示模型是否被删除
    """
    def __init__(self, model_id, model_type, model_description,model_llm_details: dict = None,model_emb_details: dict = None):
        self.model_id = model_id
        self.model_type = model_type
        self.model_description = model_description
        self.model_llm_details = model_llm_details
        self.model_emb_details = model_emb_details

    def to_dict(self):
        if self.model_type == ModelType.LLM.value:
            return {"_id": self.model_id,"model_id": self.model_id, "model_type": self.model_type,
                                 "model_description": self.model_description, "model_llm_details": self.model_llm_details,"model_emb_details": None, "is_remove": 0}
        if self.model_type == ModelType.EMBEDDIND.value:
            return {"_id": self.model_id,"model_id": self.model_id, "model_type": self.model_type,
                                 "model_description": self.model_description, "model_llm_details": None,"model_emb_details": self.model_emb_details, "is_remove": 0}
        else:
            return {"_id": self.model_id,"model_id": self.model_id, "model_type": self.model_type,
                                 "model_description": self.model_description, "model_llm_details": None,"model_emb_details": None, "is_remove": 0}


class Model_Return_Entity(object):
    """
        功能说明：根据model_id, model_type, model_description,model_run_details，返回模型列表实体
        返回的字典中不涉及"is_remove"相关信息
        """
    def __init__(self, model_id, model_type, model_description,model_llm_details: dict = None,model_emb_details: dict = None):
        self.model_id = model_id
        self.model_type = model_type
        self.model_description = model_description
        self.model_llm_details = model_llm_details
        self.model_emb_details = model_emb_details

    def to_dict(self):
        if self.model_type == ModelType.LLM.value:
            return {"_id": self.model_id,"model_id": self.model_id, "model_type": self.model_type,
                                 "model_description": self.model_description, "model_llm_details": self.model_llm_details}
        if self.model_type == ModelType.EMBEDDIND.value:
            return {"_id": self.model_id,"model_id": self.model_id, "model_type": self.model_type,
                                 "model_description": self.model_description, "model_emb_details": self.model_emb_details}
        else:
            return {"_id": self.model_id,"model_id": self.model_id, "model_type": self.model_type,
                                 "model_description": self.model_description}
    
