from typing import Any
from fastapi import APIRouter, Body, BackgroundTasks, File, UploadFile, Form
import uuid
import os
import tempfile
from pai_rag.core.rag_service import rag_service
from pai_rag.app.api.models import (
    RagQuery,
    LlmQuery,
    RetrievalQuery,
    RagResponse,
    LlmResponse,
    DataInput,
)

router = APIRouter()


@router.post("/query")
async def aquery(query: RagQuery) -> RagResponse:
    return await rag_service.aquery(query)


@router.post("/query/llm")
async def aquery_llm(query: LlmQuery) -> LlmResponse:
    return await rag_service.aquery_llm(query)


@router.post("/query/retrieval")
async def aquery_retrieval(query: RetrievalQuery):
    return await rag_service.aquery_retrieval(query)


@router.post("/query/agent")
async def aquery_agent(query: LlmQuery) -> LlmResponse:
    return await rag_service.aquery_agent(query)


@router.patch("/config")
async def aupdate(new_config: Any = Body(None)):
    rag_service.reload(new_config)
    return {"msg": "Update RAG configuration successfully."}


@router.get("/config")
async def aconfig():
    return rag_service.get_config()


@router.post("/upload_data")
def load_data(input: DataInput, background_tasks: BackgroundTasks):
    task_id = uuid.uuid4().hex
    background_tasks.add_task(
        rag_service.add_knowledge_async,
        task_id=task_id,
        file_dir=input.file_path,
        enable_qa_extraction=input.enable_qa_extraction,
    )
    return {"task_id": task_id}


@router.get("/get_upload_state")
def task_status(task_id: str):
    status = rag_service.get_task_status(task_id)
    return {"task_id": task_id, "status": status}


@router.post("/evaluate/response")
def evaluate_reponse():
    eval_results = rag_service.evaluate_reponse()
    return {"status": 200, "result": eval_results}


@router.post("/batch_evaluate/retrieval")
async def batch_retrieval_evaluate():
    df, eval_results = await rag_service.batch_evaluate_retrieval_and_response(
        type="retrieval"
    )
    return {"status": 200, "result": eval_results}


@router.post("/batch_evaluate/response")
async def batch_response_evaluate():
    df, eval_results = await rag_service.batch_evaluate_retrieval_and_response(
        type="response"
    )
    return {"status": 200, "result": eval_results}


@router.post("/batch_evaluate")
async def batch_evaluate():
    df, eval_results = await rag_service.batch_evaluate_retrieval_and_response(
        type="all"
    )
    return {"status": 200, "result": eval_results}


@router.post("/upload_local_data")
async def upload_local_data(
    file: UploadFile = File(),
    faiss_path: str = Form(None),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    task_id = uuid.uuid4().hex
    if not file:
        return {"message": "No upload file sent"}
    else:
        fn = file.filename
        tmpdir = tempfile.mkdtemp()
        save_file = os.path.join(tmpdir, f"{task_id}_{fn}")
        with open(save_file, "wb") as f:
            data = await file.read()
            f.write(data)
            f.close()

        background_tasks.add_task(
            rag_service.add_knowledge_async,
            task_id=task_id,
            file_dir=tmpdir,
            faiss_path=faiss_path,
            enable_qa_extraction=False,
        )

    return {"task_id": task_id}
