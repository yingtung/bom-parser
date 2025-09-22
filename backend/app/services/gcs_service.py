import json
import uuid
from datetime import timedelta

import pandas as pd
from google.cloud import storage
from google.cloud.documentai import Document

from app.core.config import settings
from app.services.document_ai import extract_items
from app.utils import convert_keys, extract_numeric_value, logger


def generate_signed_url_for_upload(file_name: str, content_type: str) -> dict:
    """
    Generate a signed url for file uploaded to google cloud storage

    Args:
        file_name: original file name`
        content_type: mime type of the file

    Returns:
        the dictionary which contains the uploaded url and file key
    """
    try:
        # 建立一個獨特的檔案名稱，以避免命名衝突
        unique_file_key = f"{uuid.uuid4()}"
        bucket_name = settings.get_upload_bucket_name(unique_file_key)

        # 在函式內部，我們確保設定已載入
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)

        blob = bucket.blob(file_name)

        # 生成簽名 URL
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=60),  # URL 有效時間設定為 60 分鐘
            method="PUT",
            content_type=content_type,
        )

        return {"signed_url": url, "file_key": unique_file_key, "file_name": file_name}

    except Exception as e:
        # 在服務層級處理錯誤，並將其傳遞給 API 端點
        raise RuntimeError(f"無法生成簽名 URL: {e}")


def generate_signed_url_for_download(gcs_download_name: str):
    storage_client = storage.Client()
    # gcs_download_name 形如: "<bucket>/download/<file_key>/<file_name>"
    # 我們需要移除前面的 bucket 名稱，只保留路徑部分作為 blob 路徑
    split_gcs_download_name = gcs_download_name.split("/")
    blob_path = "/".join(split_gcs_download_name[1:])
    bucket = storage_client.bucket(settings.GCS_BUCKET_NAME)
    blob = bucket.blob(blob_path)

    url = blob.generate_signed_url(
        version="v4", expiration=timedelta(minutes=60), method="GET"
    )
    return {
        "signed_url": url,
        "file_key": split_gcs_download_name[2],
        "file_name": split_gcs_download_name[-1],
    }


def download_and_process_docai_results(
    gcs_process_name: str, gcs_download_name: str
) -> str:
    """
    從 GCS 下載 Document AI 的批次處理結果，並將其轉換為 Excel。

    Args:
        gcs_process_name: Document AI 處理結果的 GCS 目錄。
        gcs_download_name: 最終 Excel 檔案的目標 GCS 儲存桶。

    Returns:
        最終 Excel 檔案的 GCS 路徑。
    """
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(settings.GCS_BUCKET_NAME)
        prefix = "/".join(gcs_process_name.split("/")[1:])

        # 列出並下載所有結果檔案
        blobs = bucket.list_blobs(prefix=prefix)

        all_bom = []
        all_cpl = []
        for blob in blobs:
            # 確保只處理 JSON 檔案
            logger.info(f"正在處理 {blob.name}")
            if blob.name.endswith(".json"):
                json_data = json.loads(blob.download_as_bytes().decode("utf-8"))
                json_data = convert_keys(json_data)
                document = Document(**json_data)
                items = extract_items(document)
                all_bom += items.bom_items
                all_cpl += items.cpl_items
        logger.info(f"BOM 實體數量: {len(all_bom)}")
        logger.info(f"CPL 實體數量: {len(all_cpl)}")

        if not all_bom and not all_cpl:
            raise RuntimeError("未在 Document AI 處理結果中找到任何 BOM 或 CPL 實體。")

        # Create DataFrames first
        bom_df = pd.DataFrame([bom.dict() for bom in all_bom])
        cpl_df = pd.DataFrame([cpl.dict() for cpl in all_cpl])

        # Save to temporary Excel file
        import io

        excel_output = io.BytesIO()
        with pd.ExcelWriter(excel_output, engine="openpyxl") as writer:
            bom_df.to_excel(
                writer, sheet_name="BOM", index=False
            )  # index=False prevents writing the DataFrame index
            cpl_df.to_excel(writer, sheet_name="CPL", index=False)

        excel_output.seek(0)

        # 上傳最終的 Excel 檔案到 GCS
        final_file_name = f"{'/'.join(gcs_download_name.split('/')[1:])}/output.xlsx"
        final_blob = storage_client.bucket(settings.GCS_BUCKET_NAME).blob(
            final_file_name
        )
        final_blob.upload_from_file(
            excel_output,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        logger.info(
            f"Excel 檔案已成功上傳到 GCS：gs://{settings.GCS_BUCKET_NAME}/{final_file_name}"
        )
        return f"{settings.GCS_BUCKET_NAME}/{final_file_name}"

    except Exception as e:
        raise RuntimeError(f"處理 Document AI 結果時發生錯誤：{e}")


def download_converted_excel(gcs_download_name: str) -> bytes:
    """
    從 GCS 下載已轉換完成的 Excel 檔案內容（bytes）。

    Args:
        gcs_download_name: 下載目錄的 GCS 名稱，例如 settings.get_download_bucket_name(file_key)
        file_name: 下載檔案名稱，預設為 "output.xlsx"

    Returns:
        Excel 檔案的位元組內容。

    Raises:
        RuntimeError: 當檔案不存在或下載失敗時。
    """
    try:
        storage_client = storage.Client()
        # gcs_download_name 形如: "<bucket>/download/<file_key>"
        # 我們需要移除前面的 bucket 名稱，只保留路徑部分作為 blob 路徑
        blob_path_prefix = "/".join(gcs_download_name.split("/")[1:])
        blob_path = f"{blob_path_prefix}"

        bucket = storage_client.bucket(settings.GCS_BUCKET_NAME)
        blob = bucket.blob(blob_path)

        if not blob.exists():
            raise RuntimeError(
                f"找不到檔案：gs://{settings.gcs_bucket_name}/{blob_path}"
            )

        return blob.download_as_bytes()
    except Exception as e:
        raise RuntimeError(f"下載 Excel 檔案失敗：{e}")
