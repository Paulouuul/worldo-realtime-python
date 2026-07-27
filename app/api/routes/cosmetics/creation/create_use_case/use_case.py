import logging
import time
import cuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pydantic import BaseModel

from app.core.database import db
from app.core.r2 import r2_client
from app.utils.image_utils import convert_to_webp, add_animated_suffix, ConvertOptions

logger = logging.getLogger(__name__)

class CreateCosmeticFrameRequest(BaseModel):
    user_id: str
    name: str
    description: Optional[str] = None
    package_id: str
    image: Dict[str, Any]
    thumbnail: Optional[Dict[str, Any]] = None

class CreateCosmeticFrameUseCase:
    MAX_FRAME_SIZE = 5 * 1024 * 1024  # 5MB
    MAX_FRAME_GIF = 3 * 1024 * 1024   # 3MB
    MAX_THUMB_SIZE = 2 * 1024 * 1024  # 2MB
    MAX_THUMB_GIF = 1 * 1024 * 1024   # 1MB
    MAX_NAME_SIZE = 50
    MAX_DESCRIPTION_SIZE = 500
    
    ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'jfif'}
    ALLOWED_MIME_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/jfif'}
    
    def __init__(self):
        self._uploaded_image_path = None
        self._uploaded_thumbnail_path = None

    async def execute(self, payload: dict) -> tuple[Dict[str, Any], int]:
        """Recebe o dicionário payload diretamente do Router"""
        try:
            logger.info(f"Iniciando criação de cosmético para o usuário: {payload.get('user_id')}")
            
            # Validação Rápida (Fail Fast)
            if not payload.get('name') or not payload.get('package_id'):
                raise ValueError("Campos obrigatórios inválidos ou faltando (name, package_id)")
            
             # Validação de tamanho do nome
            name = " ".join(payload.get('name', '').strip().split())
            if len(name) > self.MAX_NAME_SIZE:
                raise ValueError(f"Nome deve ter no máximo {self.MAX_NAME_SIZE} caracteres")
            if len(name) < 3:
                raise ValueError("Nome deve ter pelo menos 3 caracteres")
                
            # Validação de tamanho da descrição
            description = payload.get('description')
            if description is not None:
                description = str(description).strip()
                if len(description) > self.MAX_DESCRIPTION_SIZE:
                    raise ValueError(f"Descrição deve ter no máximo {self.MAX_DESCRIPTION_SIZE} caracteres")
            else:
                description = None
                
                    
            if not payload.get('image'):
                raise ValueError("Imagem principal é obrigatória")

            request = CreateCosmeticFrameRequest(**payload)
            
            # Validações de Arquivo
            self._validate_file(request.image, "moldura", self.MAX_FRAME_SIZE, self.MAX_FRAME_GIF)
            if request.thumbnail:
                self._validate_file(request.thumbnail, "miniatura", self.MAX_THUMB_SIZE, self.MAX_THUMB_GIF)
                
            # Validação de Regras de Negócio (Pacote e Moedas)
            package = await self._get_package(request.package_id)
            if not package:
                return {"error": "Pacote inválido"}, 400
                
            user_coins = await self._get_user_coins(request.user_id)
            total_cost = int(package['totalCost']) 
            if user_coins < total_cost:
                return {
                    "error": f"Moedas insuficientes. Você precisa de {total_cost} moedas."
                }, 400

            # Processar Uploads (Memória -> WebP -> R2)
            timestamp = int(time.time() * 1000) # Usando ms para evitar conflitos
            new_image_url, self._uploaded_image_path = await self._process_frame(request, timestamp)
            
            if request.thumbnail:
                new_thumb_url, self._uploaded_thumbnail_path = await self._process_thumbnail(request, timestamp)
            else:
                new_thumb_url = new_image_url

            # Transação no Banco de Dados
            try:
                # O bloco "async with db.transaction()" garante que se algo falhar,
                # nenhuma query desta sessão será salva no PostgreSQL.
                async with db.transaction():
                    # Debitar moedas
                    updated_user = await db.fetch_one(
                        """UPDATE users SET coins = coins - $1 WHERE id = $2 RETURNING coins""",
                        total_cost, request.user_id
                    )
                    
                    if updated_user['coins'] < 0:
                        raise RuntimeError("INSUFFICIENT_FUNDS")
                    frame_id = cuid.cuid()
                    now = datetime.now(timezone.utc).replace(tzinfo=None)
                    # Criar a moldura (Cosmetic Frame)
                    frame = await db.fetch_one(
                        """
                        INSERT INTO cosmetic_frame (id, name, description, "imageUrl", "thumbnailUrl", rarity, stock, "createdBy", "createdAt", "updatedAt")
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                        RETURNING *
                        """,
                        frame_id, name, description, new_image_url, new_thumb_url,
                        package['rarity'], int(package['quantity']), request.user_id, now, now
                    )
                    
                    # Adicionar itens ao inventário do usuário
                    for _ in range(int(package['quantity'])):
                        item_id = cuid.cuid()
                        await db.execute(
                            """INSERT INTO user_frame_item ("id","frameId", "ownerId", "createdAt", "updatedAt") VALUES ($1, $2, $3, $4, $5)""",
                            item_id, frame['id'], request.user_id, now, now
                        )
                        
                    # Registrar histórico da transação
                    transaction_id = cuid.cuid() 
                    await db.execute(
                        """
                        INSERT INTO coin_transaction ("id", "userId", amount, balance, type, description, "createdAt")
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """,
                        transaction_id, request.user_id, -total_cost, updated_user['coins'], 'spend',
                        f"Criação de moldura: {name} ({package['rarity']}) - Pacote {package['name']}", now
                    )
                    
            except Exception as db_err:
                logger.error(f"Falha na transação do BD: {db_err}")
                raise db_err # Relança para ser pego pelo bloco exterior e acionar o Rollback no R2

            # Sucesso Total
            return {
                "success": True,
                "frame": dict(frame),
                "message": f"Moldura criada! {int(package['quantity'])} unidade(s) do pacote {package['name']} adicionadas ao seu inventário."
            }, 201

        except ValueError as e:
            await self._rollback()
            return {"error": str(e)}, 400
        except RuntimeError as e:
            await self._rollback()
            if str(e) == "INSUFFICIENT_FUNDS":
                return {"error": "Moedas insuficientes"}, 400
            return {"error": "Erro interno de processamento"}, 500
        except Exception as e:
            logger.error(f"Erro crítico ao criar moldura: {e}")
            await self._rollback()
            return {"error": "Erro interno ao criar moldura", "details": str(e)}, 500

    # MÉTODOS DE VALIDAÇÃO E BD

    def _validate_file(self, file_data: Dict, file_type: str, max_size: int, max_gif_size: int):
        filename = file_data.get('filename', '')
        content_type = file_data.get('content_type', '')
        size = file_data.get('size', 0)
        extension = filename.split('.')[-1].lower() if filename else ''
        
        if content_type not in self.ALLOWED_MIME_TYPES or extension not in self.ALLOWED_EXTENSIONS:
            raise ValueError(f"Formato da {file_type} não suportado. Use JPG, PNG, GIF ou JFIF.")
        
        if content_type == 'image/gif' and size > max_gif_size:
            raise ValueError(f"GIF para {file_type} deve ter no máximo {max_gif_size // 1024 // 1024}MB.")
            
        if size > max_size:
            raise ValueError(f"{file_type.capitalize()} deve ter no máximo {max_size // 1024 // 1024}MB.")

    async def _get_package(self, package_id: str):
        return await db.fetch_one('SELECT * FROM cosmetic_creation_package WHERE id = $1', package_id)

    async def _get_user_coins(self, user_id: str) -> int:
        user = await db.fetch_one('SELECT coins FROM users WHERE id = $1', user_id)
        return int(user['coins']) if user else 0

    # MÉTODOS DE PROCESSAMENTO DE IMAGEM

    async def _process_frame(self, request: CreateCosmeticFrameRequest, timestamp: int):
        is_gif = request.image['content_type'] == 'image/gif'
        image_bytes = request.image['data'] # Bytes puros lidos do router
        
        converted = convert_to_webp(
            image_bytes,
            request.image['content_type'],
            ConvertOptions(
                format='webp-animated' if is_gif else 'webp', 
                quality=70 if is_gif else 75, 
                width=512, 
                height=512, 
                fit='inside'
            )
        )
        
        filename = f"image-{timestamp}.webp"
        final_filename = add_animated_suffix(filename, is_gif)
        path = f"frames/{timestamp}-{request.user_id}/{final_filename}"
        
        url = await r2_client.upload_public(converted.buffer, path, 'image/webp')
        return url, path

    async def _process_thumbnail(self, request: CreateCosmeticFrameRequest, timestamp: int):
        is_gif = request.thumbnail['content_type'] == 'image/gif'
        thumb_bytes = request.thumbnail['data']
        
        converted = convert_to_webp(
            thumb_bytes,
            request.thumbnail['content_type'],
            ConvertOptions(
                format='webp-animated' if is_gif else 'webp', 
                quality=70 if is_gif else 75, 
                width=512, 
                height=512, 
                fit='cover'
            )
        )
        
        filename = f"thumbnail-{timestamp}.webp"
        final_filename = add_animated_suffix(filename, is_gif)
        path = f"frames/{timestamp}-{request.user_id}/{final_filename}"
        
        url = await r2_client.upload_public(converted.buffer, path, 'image/webp')
        return url, path

    # ROLLBACK DE ARQUIVOS NO R2

    async def _rollback(self):
        """Em caso de falha, exclui os arquivos enviados para o R2 para não virar lixo de bucket"""
        if self._uploaded_image_path:
            await r2_client.delete_file(self._uploaded_image_path, is_public=True)
            logger.info(f"Rollback executado: moldura deletada -> {self._uploaded_image_path}")
            
        if self._uploaded_thumbnail_path and self._uploaded_thumbnail_path != self._uploaded_image_path:
            await r2_client.delete_file(self._uploaded_thumbnail_path, is_public=True)
            logger.info(f"Rollback executado: thumbnail deletada -> {self._uploaded_thumbnail_path}")