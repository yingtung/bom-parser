from fastapi import APIRouter, Depends
from pydantic.networks import EmailStr

from app.api.deps import get_current_active_superuser
from app.core.config import settings
from app.models import Message
from app.models.utils import SystemInfoResponse
from app.utils import generate_test_email, send_email

router = APIRouter(prefix="/utils", tags=["utils"])


@router.post(
    "/test-email/",
    dependencies=[Depends(get_current_active_superuser)],
    status_code=201,
)
def test_email(email_to: EmailStr) -> Message:
    """
    Test emails.
    """
    email_data = generate_test_email(email_to=email_to)
    send_email(
        email_to=email_to,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )
    return Message(message="Test email sent")


@router.get("/health-check/")
async def health_check() -> bool:
    return True


@router.get("/system/info", response_model=SystemInfoResponse)
async def get_operation_info() -> SystemInfoResponse:
    """
    Get GCP process version and configuration information.
    """
    return SystemInfoResponse(
        gcp_processor_version=settings.GCP_PROCESSOR_VERSION,
        gcp_project_id=settings.GCP_PROJECT_ID,
        gcp_location=settings.GCP_LOCATION,
        gcp_processor_id=settings.GCP_PROCESSOR_ID,
    )


@router.get("/sentry-debug")
async def trigger_error():
    division_by_zero = 1 / 0  # noqa: F841
