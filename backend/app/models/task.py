from enum import Enum

from pydantic import BaseModel


class CeleryTaskStatus(str, Enum):
    PENDING = "PENDING"
    STARTED = "STARTED"
    RETRY = "RETRY"
    FAILURE = "FAILURE"
    SUCCESS = "SUCCESS"


class TaskStatusResponse(BaseModel):
    status: CeleryTaskStatus
