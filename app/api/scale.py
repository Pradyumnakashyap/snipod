import logging

from fastapi import APIRouter, Depends, status
from kubernetes.client import V1TokenReview
from pydantic import BaseModel, Field

from core.security import verify_token
from services.scale_in import handle_scale_in

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Scaling"])


class ScaleInRequest(BaseModel):
    pod_name: str = Field(..., description="Name of the pod to remove", examples=["my-app-0"])


class ScaleInResponse(BaseModel):
    status: int
    message: str
    deployment_name: str


@router.post(
    "/scale_in",
    response_model=ScaleInResponse,
    status_code=status.HTTP_200_OK,
    description="Scale in by removing a specific pod. Finds the owning Deployment via ownerReferences, "
    "annotates the pod with deletion-cost -1, and decreases replicas by 1.",
    responses={
        200: {"description": "Scale-in completed"},
        401: {"description": "Authentication failed"},
        403: {"description": "Forbidden — namespace mismatch"},
        404: {"description": "Pod or owning Deployment not found"},
        422: {"description": "Cannot scale below 1 replica"},
    },
)
def scale_in(
    body: ScaleInRequest,
    token_review: V1TokenReview = Depends(verify_token),
):
    from core.security import get_client_namespace

    namespace = get_client_namespace(token_review)
    result = handle_scale_in(namespace=namespace, pod_name=body.pod_name)
    return ScaleInResponse(
        status=status.HTTP_200_OK,
        message=f"Scaled in Deployment/{result['deployment_name']} by removing pod {body.pod_name}",
        deployment_name=result["deployment_name"],
    )
