from sqlmodel import SQLModel


class SystemInfoResponse(SQLModel):
    gcp_processor_version: str
    gcp_project_id: str | None
    gcp_location: str
    gcp_processor_id: str | None

