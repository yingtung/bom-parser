import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from sqlmodel import Field, Relationship, SQLModel

from app.core.config import settings


class FileType(str, Enum):
    PDF = "application/pdf"


class DocumentBase(SQLModel):
    """Base model for Document with common fields."""

    file_key: str = Field(index=True, description="Unique identifier for the file")
    file_name: str = Field(description="Original name of the uploaded file")
    file_type: str = Field(description="MIME type of the file (e.g., application/pdf)")
    gcs_upload_uri: str | None = Field(
        default=None, description="GCS URI for the uploaded file"
    )
    gcs_process_uri: str | None = Field(
        default=None, description="GCS URI for the processed file"
    )
    gcs_download_uri: str | None = Field(
        default=None, description="GCS URI for the downloaded file"
    )


class DocumentCreate(DocumentBase):
    """Schema for creating a new document."""

    pass


class DocumentUpdate(SQLModel):
    """Schema for updating a document."""

    file_name: str | None = None
    gcs_upload_uri: str | None = None
    gcs_process_uri: str | None = None
    gcs_download_uri: str | None = None
    file_type: str | None = None


class DocumentRead(DocumentBase):
    """Schema for reading document data."""

    id: str
    created_at: datetime
    updated_at: datetime
    owner_id: str


class ProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class BOMShema(SQLModel):
    """Represents a single BOM item."""

    page: str | None = None
    line_no: str | None = None
    bom_pt: str | None = None
    bom_description: str | None = None
    bom_size: str | None = None
    bom_quantity: str | None = None
    bom_item_code: str | None = None


class CPLShema(SQLModel):
    """Represents a single CPL item."""

    page: str | None = None
    line_no: str | None = None
    cpl_cut_piece: str | None = None
    cpl_length: str | None = None
    cpl_size: str | None = None


class Items(SQLModel):
    bom_items: list[BOMShema]
    cpl_items: list[CPLShema]


class ProcessingRequest(SQLModel):
    """Request model for processing a BOM document."""

    file_path: str
    mime_type: FileType = FileType.PDF


class ProcessingResponse(SQLModel):
    """Response model for processing results."""

    status: ProcessingStatus
    message: str
    bom_items: list[BOMShema] | None = None
    raw_data: dict[str, Any] | None = None
    error: str | None = None


class HealthResponse(SQLModel):
    """Health check response."""

    status: str
    app_name: str
    version: str


class SignedUrlRequest(SQLModel):
    """用於生成簽名 URL 的請求模型。"""

    file_name: str
    content_type: str

    def to_document_create(self):
        file_key = f"{uuid.uuid4()}"
        return DocumentCreate(
            file_key=file_key,
            file_name=self.file_name,
            file_type=self.content_type,
            gcs_upload_uri=settings.get_upload_bucket_name(file_key),
            gcs_process_uri=settings.get_process_bucket_name(file_key),
            gcs_download_uri=settings.get_download_bucket_name(file_key),
        )


class SignedUrlRespsonse(SQLModel):
    """用於生成簽名 URL 的請求模型。"""

    signed_url: str
    file_key: str | None = None
    file_name: str | None = None


class FileProcessedRequest(SQLModel):
    file_key: str
    file_name: str


class FileProcessedResponse(SQLModel):
    message: str
    task_id: str
    file_key: str


class ConvertingRequest(SQLModel):
    """Request model for converting document json to excel."""

    file_key: str


class OperationStatusRequest(SQLModel):
    """Request model for checking operation status."""

    operation_name: str


class OperationStatusResponse(SQLModel):
    """Response model for operation status."""

    done: bool
