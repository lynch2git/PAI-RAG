# Copyright (c) Alibaba Cloud PAI.
# SPDX-License-Identifier: Apache-2.0
# deling.sc

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import StreamingResponse

import gradio as gr
from modules.LLMService import LLMService
import time
import os
from pydantic import BaseModel
import json
from args import parse_args
from modules.UI import *
import requests

def init_args(args):
    args.config = 'configs/config_holo.json'
    args.prompt_engineering = 'general'
    args.embed_model = "SGPT-125M-weightedmean-nli-bitfit"
    args.embed_dim = 768
    # args.vectordb_type = 'Elasticsearch'
    args.upload = False
    # args.user_query = None
    # args.query_type = "retrieval_llm"

_global_args = parse_args()
init_args(_global_args)

service = LLMService(_global_args)
with open(_global_args.config) as f:
    _global_cfg = json.load(f)
    
class Query(BaseModel):
    question: str
    topk: int | None = 30
    topp: float | None = 0.8
    temperature: float | None = 0.7
    vector_topk: int | None = 3
    score_threshold: float | None = 0.5
    use_chat_stream: bool | None = False

class LLMQuery(BaseModel):
    question: str
    topk: int | None = 30
    topp: float | None = 0.8
    temperature: float | None = 0.7
    use_chat_stream: bool | None = False
    
class VectorQuery(BaseModel):
    question: str
    vector_topk: int | None = 3
    score_threshold: float | None = 0.5

host_ = "127.0.0.1"
app = FastAPI(host=host_)

@app.post("/chat/llm")
async def query_by_llm(query: LLMQuery):
    async def stream_results():
        ans, lens, _ = service.query_only_llm(query = query.question, llm_topK=query.topk, llm_topp=query.topp, llm_temp=query.temperature) 
        for cha in ans:
            ret = {"response": cha, "tokens": lens}
            yield (json.dumps(ret,ensure_ascii=False) + '\0')
    if query.use_chat_stream:
        return StreamingResponse(stream_results())
    else:
        ans, lens, _ = service.query_only_llm(query = query.question, llm_topK=query.topk, llm_topp=query.topp, llm_temp=query.temperature) 
        return {"response": ans, "tokens": lens}

@app.post("/chat/vectorstore")
async def query_by_vectorstore(query: VectorQuery):
    ans, lens = service.query_only_vectorstore(query = query.question, topk=query.vector_topk, score_threshold=query.score_threshold) 
    return {"response": ans, "tokens": lens}

@app.post("/chat/langchain")
async def query_by_langchain(query: Query):
    async def stream_results():
        ans, lens, _ = service.query_retrieval_llm(query = query.question, topk=query.vector_topk, score_threshold=query.score_threshold, llm_topK=query.topk, llm_topp=query.topp, llm_temp=query.temperature)
        for cha in ans:
            ret = {"response": cha, "tokens": lens}
            yield (json.dumps(ret,ensure_ascii=False) + '\0')
    if query.use_chat_stream:
        return StreamingResponse(stream_results())
    else:
        ans, lens, _ = service.query_retrieval_llm(query = query.question, topk=query.vector_topk, score_threshold=query.score_threshold, llm_topK=query.topk, llm_topp=query.topp, llm_temp=query.temperature)
        return {"response": ans, "tokens": lens}

@app.post("/uploadfile")
async def create_upload_file(file: UploadFile | None = None):
    if not file:
        return {"message": "No upload file sent"}
    else:
        fn = file.filename
        save_path = f'./file/'
        if not os.path.exists(save_path):
            os.mkdir(save_path)
    
        save_file = os.path.join(save_path, fn)
    
        f = open(save_file, 'wb')
        data = await file.read()
        f.write(data)
        f.close()
        service.upload_custom_knowledge(f.name,200,0)
        return {"response": "success"}


# @app.post("/config")
# async def create_config_json_file(file: UploadFile | None = None):
#     if not file:
#         return {"message": "No upload config json file sent"}
#     else:
#         fn = file.filename
#         save_path = f'./config/'
#         if not os.path.exists(save_path):
#             os.mkdir(save_path)
    
#         save_file = os.path.join(save_path, fn)
    
#         f = open(save_file, 'wb')
#         data = await file.read()
#         f.write(data)
#         f.close()
#         with open(f.name) as c:
#             cfg = json.load(c)
#         _global_args.embed_model = cfg['embedding']['embedding_model']
#         _global_args.vectordb_type = cfg['vector_store']
#         if 'query_topk' not in cfg:
#             cfg['query_topk'] = 4
#         if 'prompt_template' not in cfg:
#             cfg['prompt_template'] = "基于以下已知信息，简洁和专业的来回答用户的问题。如果无法从中得到答案，请说 \"根据已知信息无法回答该问题\" 或 \"没有提供足够的相关信息\"，不允许在答案中添加编造成分，答案请使用中文。\n=====\n已知信息:\n{context}\n=====\n用户问题:\n{question}"
#         if cfg.get('create_docs') is None:
#             cfg['create_docs'] = {}
#         cfg['create_docs']['chunk_size'] = 200
#         cfg['create_docs']['chunk_overlap'] = 0
#         cfg['create_docs']['docs_dir'] = 'docs/'
#         cfg['create_docs']['glob'] = "**/*"
            
#         connect_time = service.init_with_cfg(cfg,_global_args)
#         return {"response": "success"}
    
def check_health(url, authorization="="):
    while True:
        try:
            full_url = url
            response = requests.get(
                full_url, 
                headers={
                    'Authorization': authorization,
                    'Content-Type': 'application/json'
                }, 
                timeout=3
            )
            if response.ok:  # .ok covers all 2xx codes
                print("Server is up and running, starting app...")
                return True
            else:
                print(f"Server is down, status code: {response.status_code}, retrying in 3 seconds...")
        except requests.exceptions.RequestException as e:
            print("Exception occurred: ", e)
        time.sleep(3)

# url_ = "http://127.0.0.1:8000"
# authorization_ = "="
 
URL_ = os.getenv('URL')
if URL_ is not None:
    if check_health(URL_):
        _global_cfg['EASCfg']['url'] = URL_
        _global_cfg['EASCfg']['token'] = "NOToken"
        ui = create_ui(service,_global_args,_global_cfg)
        ui.queue()
        app = gr.mount_gradio_app(app, ui, path='')
else:
    ui = create_ui(service,_global_args,_global_cfg)
    ui.queue()
    app = gr.mount_gradio_app(app, ui, path='')
    