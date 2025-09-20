from fastapi import APIRouter, Depends, HTTPException
from requests import session
from starlette.status import (
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from app.api.deps import (
    get_current_user,
    get_db,
    get_document_ai_service_dependency,
)
from app.core.config import settings
from app.models.document import (
    ConvertingRequest,
    FileProcessedRequest,
    FileProcessedResponse,
    OperationStatusRequest,
    OperationStatusResponse,
    SignedUrlRequest,
    SignedUrlRespsonse,
)
from app.services.document_ai import DocumentAIService
from app.services.gcs_service import (
    generate_signed_url_for_download,
    generate_signed_url_for_upload,
)
from app.tasks import convert_to_excel_task, process_document_task
from app.utils import logger

router = APIRouter(
    prefix="/document", tags=["document"], dependencies=[Depends(get_current_user)]
)


@router.post(
    "/upload",
    description="receive file information and return a signed url for frontend direct upload to GCS",
)
async def generate_signed_url_endpoint(request: SignedUrlRequest) -> SignedUrlRespsonse:
    result = generate_signed_url_for_upload(request.file_name, request.content_type)
    return SignedUrlRespsonse(**result)


@router.post(
    "/process",
    description="Receive the file upload completion notification and then add the document AI task to the Celery task queue.",
)
async def process_uploaded_file(request: FileProcessedRequest) -> FileProcessedResponse:
    # 建立 GCS 檔案的 URI
    gcs_input_uri = (
        f"gs://{settings.get_upload_bucket_name(request.file_key)}/{request.file_name}"
    )
    gcs_output_uri = f"gs://{settings.get_process_bucket_name(request.file_key)}"

    # 將任務放入 Celery 佇列
    task = process_document_task.delay(
        gcs_input_uri=gcs_input_uri,
        gcs_output_uri=gcs_output_uri,
        field_mask="entities",
    )

    return FileProcessedResponse(
        message="處理任務已排入佇列",
        task_id=task.id,
        file_key=request.file_key,
    )


@router.post("/convert", description="convert the processed file to excel")
async def convert_processed_file_to_excel(request: ConvertingRequest):
    # 將任務放入 Celery 佇列
    task = convert_to_excel_task.delay(
        gcs_process_name=settings.get_process_bucket_name(request.file_key),
        gcs_download_name=settings.get_download_bucket_name(request.file_key),
    )

    return FileProcessedResponse(
        message="處理任務已排入佇列", task_id=task.id, file_key=request.file_key
    )


@router.post("/test", description="convert the processed file to excel")
async def test(request: ConvertingRequest):
    from app.services.gcs_service import download_and_process_docai_results

    gcs_process_name = settings.get_process_bucket_name(request.file_key)
    gcs_download_name = settings.get_download_bucket_name(request.file_key)
    # 將任務放入 Celery 佇列
    final_excel_path = download_and_process_docai_results(
        gcs_process_name, gcs_download_name
    )
    logger.info(f"Excel 轉換完成：{final_excel_path}")
    return {
        "gcs_download_path": final_excel_path,
    }


@router.get("/download", description="download excel file from gcs")
async def download_from_gcs(gcs_download_path: str):
    result = generate_signed_url_for_download(gcs_download_path)
    return SignedUrlRespsonse(**result)


@router.post(
    "/operation",
    description="get the done status of the document ai operation",
    response_model=OperationStatusResponse,
)
async def get_operation(
    request: OperationStatusRequest,
    document_ai_service: DocumentAIService = Depends(
        get_document_ai_service_dependency
    ),
) -> OperationStatusResponse:
    operation = document_ai_service.get_operation(operation_name=request.operation_name)
    logger.debug(operation.metadata)
    if operation.error.message:
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{operation.error.message}",
        )
    logger.debug(operation.metadata.value.decode("utf-8", errors="ignore"))
    return OperationStatusResponse(done=operation.done)
