# app/api/routes/profile/router.py
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from app.utils.response import success_response, error_response
import logging
from app.auth.dependencies import get_current_user
from app.auth.schemas import UserInfo
from .update_use_case.use_case import UpdateProfileUseCase

logger = logging.getLogger(__name__)
router = APIRouter()

@router.put("/update", summary="Atualizar meu perfil")
async def update_my_profile(
    user: Annotated[UserInfo, Depends(get_current_user)],
    name: str = Form(...),
    username: str = Form(...),
    bio: str = Form(""),
    location: str = Form(""),
    website: str = Form(""),
    avatar: Optional[UploadFile] = File(None),
    cover: Optional[UploadFile] = File(None),
    removeAvatar: bool = Form(False),
    removeCover: bool = Form(False),
):
    logger.info(f"Recebendo atualização de perfil para o usuário: {user.id}")
    
    try:
        # Lê os bytes puros do UploadFile gerado pelo FormData do Next.js
        avatar_data = None
        if avatar and avatar.size > 0:
            avatar_data = {
                "filename": avatar.filename,
                "content_type": avatar.content_type,
                "size": avatar.size,
                "data": await avatar.read()  # Mantém como bytes puros
            }
        
        cover_data = None
        if cover and cover.size > 0:
            cover_data = {
                "filename": cover.filename,
                "content_type": cover.content_type,
                "size": cover.size,
                "data": await cover.read()   # Mantém como bytes puros
            }
        
        # Monta o dicionário com os dados
        payload = {
            "user_id": user.id,
            "name": name,
            "username": username,
            "bio": bio,
            "location": location,
            "website": website,
            "avatar": avatar_data,
            "cover": cover_data,
            "remove_avatar": removeAvatar,
            "remove_cover": removeCover
        }
        
        use_case = UpdateProfileUseCase()
        response_data, status_code = await use_case.execute(payload)
        
        if "error" in response_data:
            logger.error(f"Erro na edição de perfil: {response_data.get('error')}")
            error_response(response_data["error"], status_code)
        
        return success_response(response_data)

    except HTTPException:
        raise
    except ValueError as e:
        error_response(str(e), 400)
    except Exception as e:
        logger.error(f"Erro inesperado: {e}")
        error_response("Erro interno ao processar requisição", 500)