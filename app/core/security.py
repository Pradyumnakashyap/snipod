import logging

from fastapi import Header, HTTPException, Request, status
from kubernetes.client import (
    AuthenticationV1Api,
    V1TokenReview,
    V1TokenReviewSpec,
    V1TokenReviewStatus,
    V1UserInfo,
)

logger = logging.getLogger(__name__)

SERVICE_ACCOUNT_AUDIENCE = "snipod-sa"


def create_token_review(token: str) -> V1TokenReview:
    """Submit a TokenReview to the Kubernetes API server."""
    try:
        return AuthenticationV1Api().create_token_review(
            body=V1TokenReview(
                spec=V1TokenReviewSpec(
                    audiences=[SERVICE_ACCOUNT_AUDIENCE],
                    token=token,
                )
            )
        )
    except Exception as error:
        logger.error(f"TokenReview failed: {error}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token review failed",
        ) from error


def authenticate(token_review: V1TokenReview) -> None:
    """Verify the token is authenticated."""
    review_status: V1TokenReviewStatus = token_review.status
    if not review_status.authenticated:
        logger.error(f"Authentication failed: {review_status.error}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


def get_client_namespace(token_review: V1TokenReview) -> str:
    """Extract the client namespace from the token review."""
    try:
        user: V1UserInfo = token_review.status.user
        return user.username.split(":")[2]
    except (AttributeError, IndexError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cannot determine client namespace from token",
        ) from error


def assert_same_namespace(server_namespace: str, token_review: V1TokenReview) -> None:
    """Ensure the request comes from the same namespace as the server."""
    client_namespace = get_client_namespace(token_review)
    if client_namespace != server_namespace:
        logger.error(
            f"Namespace mismatch: client={client_namespace}, server={server_namespace}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request must originate from the same namespace",
        )


def verify_token(request: Request, x_token: str = Header(default=None, description="Kubernetes service account token")) -> V1TokenReview:
    """FastAPI dependency: authenticate the token and verify namespace."""
    if not x_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing x-token header",
        )
    token_review = create_token_review(x_token)
    authenticate(token_review)
    assert_same_namespace(request.app.state.namespace, token_review)
    return token_review
