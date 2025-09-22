from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.models.task import CeleryTaskStatus, TaskResultResponse, TaskStatusResponse
from app.tasks import celery_app

router = APIRouter(
    prefix="/task", tags=["tasks"], dependencies=[Depends(get_current_user)]
)


@router.get(
    "/{task_id}/status",
    description="Get the status of a Celery task",
    response_model=TaskStatusResponse,
)
async def get_task_status(task_id: str) -> TaskStatusResponse:
    """
    Get the status of a Celery task by its ID.

    Args:
        task_id: The ID of the Celery task

    Returns:
        TaskStatusResponse: The current status of the task
    """
    try:
        result = AsyncResult(task_id, app=celery_app)

        if result.state == "PENDING":
            status = CeleryTaskStatus.PENDING
        elif result.state == "STARTED":
            status = CeleryTaskStatus.STARTED
        elif result.state == "RETRY":
            status = CeleryTaskStatus.RETRY
        elif result.state == "FAILURE":
            status = CeleryTaskStatus.FAILURE
        elif result.state == "SUCCESS":
            status = CeleryTaskStatus.SUCCESS
        else:
            status = CeleryTaskStatus.PENDING

        return TaskStatusResponse(status=status)

    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Task not found: {str(e)}")


@router.get(
    "/{task_id}/result",
    description="Get the result of a completed Celery task",
    response_model=TaskResultResponse,
)
async def get_task_result(task_id: str) -> dict:
    """
    Get the result of a completed Celery task by its ID.

    Args:
        task_id: The ID of the Celery task

    Returns:
        The result of the task if completed, otherwise task status
    """
    try:
        result = AsyncResult(task_id, app=celery_app).result
        return TaskResultResponse(result=result)

    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Task not found: {str(e)}")


@router.delete(
    "/{task_id}",
    description="Cancel a Celery task",
)
async def cancel_task(task_id: str):
    """
    Cancel a Celery task by its ID.

    Args:
        task_id: The ID of the Celery task to cancel

    Returns:
        Confirmation message
    """
    try:
        celery_app.control.revoke(task_id, terminate=True)
        return {"message": f"Task {task_id} has been cancelled"}

    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Failed to cancel task: {str(e)}")
