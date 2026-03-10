from fastapi.encoders import jsonable_encoder
from typing import TypeVar
from sqlmodel import SQLModel
from app.utils.logger import setup_logger

ModelType = TypeVar("ModelType", bound=SQLModel)


logger = setup_logger(__name__)


def print_model(text: str = "", model: ModelType | list[ModelType] | dict | None = None):
    """
    Debug helper for SQLModel responses with relationships.
    Replaced side-effecting print with structured logging and return value.
    """
    payload = jsonable_encoder(model)
    try:
        logger.debug("%s %s", text, payload)
    except Exception:
        # logging failure should not break callers
        pass
    return payload
