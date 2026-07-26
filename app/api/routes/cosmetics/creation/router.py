from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
import logging
from app.auth.dependencies import get_current_user
from app.auth.schemas import UserInfo
from .create_use_case.use_case import CreateCosmeticFrameUseCase
from fastapi.responses import JSONResponse
logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/create", summary="Criar nova moldura cosmética", status_code=201)
async def create_cosmetic_frame(
    user: Annotated[UserInfo, Depends(get_current_user)],
    name: str = Form(..., description="Nome da moldura"),
    packageId: str = Form(..., description="ID do pacote selecionado (cosmetic_creation_package)"),
    description: Optional[str] = Form(None, description="Descrição opcional da moldura"),
    image: UploadFile = File(..., description="Arquivo da imagem principal"),
    thumbnail: Optional[UploadFile] = File(None, description="Arquivo da miniatura opcional"),
):
    """
    Recebe os dados do frontend (Next.js FormData), extrai as imagens e
    delega a validação, cobrança e criação para o UseCase.
    """
    logger.info("=" * 50)
    logger.info(f"INICIANDO CRIAÇÃO DE COSMÉTICO | Usuário: {user.id}")
    logger.info(f" Nome: {name}")
    logger.info(f" Pacote ID: {packageId}")
    logger.info(f"Imagem principal recebida: {image.filename} ({image.content_type}) - {image.size} bytes")
    if thumbnail:
        logger.info(f"  Miniatura recebida: {thumbnail.filename} ({thumbnail.content_type}) - {thumbnail.size} bytes")
    logger.info("=" * 50)

    try:
        # 1. Lê os bytes puros do arquivo de Imagem Principal
        image_data = None
        if image and image.size > 0:
            image_data = {
                "filename": image.filename,
                "content_type": image.content_type,
                "size": image.size,
                "data": await image.read()  # Lê os bytes puros para a memória
            }
        else:
            raise ValueError("O arquivo de imagem principal é obrigatório e não pode estar vazio.")

        # 2. Lê os bytes puros do arquivo de Miniatura (se existir)
        thumbnail_data = None
        if thumbnail and thumbnail.size > 0:
            thumbnail_data = {
                "filename": thumbnail.filename,
                "content_type": thumbnail.content_type,
                "size": thumbnail.size,
                "data": await thumbnail.read()
            }

        # 3. Monta o Payload para o Use Case (Evitando json.dumps)
        payload = {
            "user_id": user.id,
            "name": name,
            "description": description,
            "package_id": packageId,
            "image": image_data,
            "thumbnail": thumbnail_data
        }

        # 4. Executa a regra de negócios
        use_case = CreateCosmeticFrameUseCase()

        response_data, status_code = await use_case.execute(payload)

        # 5. Tratamento de Resposta

        if "error" in response_data:
            logger.error(f"Erro no use_case de cosmético: {response_data.get('error')}")
            return JSONResponse(
                            status_code=status_code,
                            content={"detail": response_data.get("error")}
            )

        logger.info("Cosmético criado com sucesso!")
        return response_data

    except ValueError as e:
        logger.warning(f"Erro de validação no router: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Erro inesperado no router de cosmético: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao processar a criação do cosmético")