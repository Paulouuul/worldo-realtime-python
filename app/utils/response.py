# app/utils/response.py
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from typing import Any
from fastapi import HTTPException
import logging
logger = logging.getLogger(__name__)

def success_response(data: Any, status_code: int = 200) -> JSONResponse:
    """Padroniza respostas de sucesso com serialização automática"""
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(data)
    )

def error_response(message: str, status_code: int = 400) -> None:
    """Padroniza respostas de erro"""
    logger.warning(f"Erro {status_code}: {message}")
    raise HTTPException(
        status_code=status_code,
        detail=message
    )