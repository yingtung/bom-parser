import os
from typing import Optional

from celery import Celery

from app.core.config import settings
from app.models.task import CeleryTaskStatus
from app.services import get_document_ai_service
from app.services.gcs_service import download_and_process_docai_results
from app.utils import logger

# 在啟動 Celery 應用程式前設定環境變數
if settings.GOOGLE_APPLICATION_CREDENTIALS:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(
        settings.GOOGLE_APPLICATION_CREDENTIALS
    )
    logger.info(
        f"Google credentials set: {os.getenv('GOOGLE_APPLICATION_CREDENTIALS')}"
    )

# 使用環境變數來構建 Redis URL，如果沒有設定則使用預設值
redis_host = os.getenv("REDIS_HOST", "redis")
redis_port = os.getenv("REDIS_PORT", "6379")
broker_url = f"redis://{redis_host}:{redis_port}/0"
result_backend = f"redis://{redis_host}:{redis_port}/1"

logger.info(f"Celery broker URL: {broker_url}")
logger.info(f"Celery result backend: {result_backend}")

# 初始化 Celery 應用程式
celery_app = Celery("tasks", broker=broker_url, backend=result_backend)

document_ai_service = get_document_ai_service()


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 60},
)
def process_document_task(
    self,
    gcs_input_uri: str,
    gcs_output_uri: str,
    field_mask: Optional[str] = None,
):
    """
    非同步處理 Document AI 任務。

    Args:
        gcs_input_uri: 上傳到 GCS 的 PDF 檔案路徑 (e.g., gs://bucket/file.pdf)。
        gcs_output_uri: document ai上傳到 GCS 的 document json 目錄路徑 (e.g., bucket/process)。
        field_mask: "text,entities,pages.pageNumber"  # Optional. The fields to return in the Document object.

    """
    logger.info(f"開始處理文件：{gcs_input_uri}, 目標目錄路徑： {gcs_output_uri}")
    logger.info(f"Task ID: {self.request.id}, Retry count: {self.request.retries}")

    try:
        # 觸發批次處理
        operation = document_ai_service.batch_process(
            gcs_input_uri=gcs_input_uri,
            gcs_output_uri=gcs_output_uri,
            field_mask=field_mask,
        )
        logger.info(f"Document AI 批次處理任務已觸發: {operation.operation.name}")

        # 此處我們不會等待任務完成，而是直接返回
        # 之後我們會討論如何查詢任務狀態
        return {
            "status": "processing_started",
            "operation_name": operation.operation.name,
        }

    except Exception as e:
        logger.error(f"處理 Document AI 任務時發生錯誤：{e}")
        logger.error(f"Error type: {type(e).__name__}")
        # 重新拋出異常以觸發重試機制
        raise e


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 60},
)
def convert_to_excel_task(self, gcs_process_name: str, gcs_download_name: str):
    """
    這是 Celery 任務，負責將 Document AI 的結果轉換為 Excel。
    """
    logger.info(f"開始轉換 Excel：{gcs_process_name} -> {gcs_download_name}")
    logger.info(f"Task ID: {self.request.id}, Retry count: {self.request.retries}")

    try:
        final_excel_path = download_and_process_docai_results(
            gcs_process_name, gcs_download_name
        )
        logger.info(f"Excel 轉換完成：{final_excel_path}")
        return {
            "status": CeleryTaskStatus.SUCCESS,
            "gcs_download_path": final_excel_path,
        }
    except Exception as e:
        logger.error(f"Excel 轉換失敗：{e}")
        logger.error(f"Error type: {type(e).__name__}")
        # 重新拋出異常以觸發重試機制
        raise e
