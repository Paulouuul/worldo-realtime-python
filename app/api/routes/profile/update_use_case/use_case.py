# app/api/routes/profile/update/use_case.py
import logging
import re
import time
from typing import Dict, Any, Optional
from pydantic import BaseModel

from app.core.database import db
from app.core.r2 import r2_client
from app.utils.image_utils import convert_to_webp, add_animated_suffix, ConvertOptions

logger = logging.getLogger(__name__)

class UpdateProfileRequest(BaseModel):
    user_id: str
    name: str
    username: str
    bio: Optional[str] = None
    location: Optional[str] = None
    website: Optional[str] = None
    avatar: Optional[Dict[str, Any]] = None
    cover: Optional[Dict[str, Any]] = None
    remove_avatar: bool = False
    remove_cover: bool = False

class UpdateProfileUseCase:
    # Limites de arquivo
    MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5MB
    MAX_COVER_SIZE = 8 * 1024 * 1024   # 8MB
    MAX_AVATAR_GIF = 3 * 1024 * 1024   # 3MB
    MAX_COVER_GIF = 5 * 1024 * 1024    # 5MB
    
    # Limites de texto
    MAX_NAME_LENGTH = 50
    MIN_NAME_LENGTH = 3
    MAX_BIO_LENGTH = 500
    MAX_LOCATION_LENGTH = 30
    MAX_WEBSITE_LENGTH = 200
    
    ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'jfif'}
    ALLOWED_MIME_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/jfif'}
    
    def __init__(self):
        self._uploaded_avatar_path = None
        self._uploaded_cover_path = None
    
    async def execute(self, payload: dict) -> tuple[Dict[str, Any], int]:
        """Recebe o dicionário payload diretamente do Router"""
        try:
            logger.info("Iniciando execução do UseCase")
            request = UpdateProfileRequest(**payload)
            
            await self._validate_request(request)
            
            new_avatar_url, uploaded_avatar_path = await self._process_avatar(request)
            new_cover_url, uploaded_cover_path = await self._process_cover(request)
            
            self._uploaded_avatar_path = uploaded_avatar_path
            self._uploaded_cover_path = uploaded_cover_path
            
            current_user = await self._get_current_user(request.user_id)
            if not current_user:
                return {"error": "Usuário não encontrado"}, 404
            
            updated_user = await self._update_user(request, new_avatar_url, new_cover_url)
            if not updated_user:
                await self._rollback()
                return {"error": "Erro ao atualizar perfil"}, 500
            
            await self._cleanup_old_files(
                current_user, uploaded_avatar_path, uploaded_cover_path,
                request.remove_avatar, request.remove_cover
            )
            
            return {
                "success": True,
                "user": {
                    "id": updated_user['id'],
                    "name": updated_user['name'],
                    "username": updated_user['username'],
                    "email": updated_user['email'],
                    "bio": updated_user.get('bio'),
                    "location": updated_user.get('location'),
                    "website": updated_user.get('website'),
                    "avatar": updated_user.get('avatar'),
                    "coverImage": updated_user.get('coverImage'),
                }
            }, 200
            
        except ValueError as e:
            await self._rollback()
            return {"error": str(e)}, 400
        except Exception as e:
            logger.error(f"Erro crítico: {e}")
            await self._rollback()
            return {"error": "Erro ao atualizar perfil"}, 500

    async def _validate_request(self, request: UpdateProfileRequest):
        
        # VALIDAÇÃO DO NOME
        name = request.name.strip()

        if not name:
            raise ValueError("Nome é obrigatório")
        
        if len(name) < self.MIN_NAME_LENGTH:
            raise ValueError(f"Nome deve ter pelo menos {self.MIN_NAME_LENGTH} caracteres")
        if len(name) > self.MAX_NAME_LENGTH:
            raise ValueError(f"Nome deve ter no máximo {self.MAX_NAME_LENGTH} caracteres")
        
        
        # VALIDAÇÃO DO USERNAME
        
        if not request.username or not request.username.strip():
            raise ValueError("Username é obrigatório")
        
        username_regex = re.compile(r'^[a-zA-Z0-9_]{3,30}$')
        sanitized_username = request.username.lower().strip()
        if not username_regex.match(sanitized_username):
            raise ValueError("Username inválido. Use apenas letras, números e underscore (3-30 caracteres)")
        
        existing_user = await db.fetch_one(
            'SELECT id FROM users WHERE username = $1 AND id != $2 AND "deletedAt" IS NULL',
            sanitized_username, request.user_id
        )
        if existing_user:
            raise ValueError("Username já em uso")
        
        
        # VALIDAÇÃO DA BIO
        
        if request.bio is not None:
            bio = request.bio.strip() if request.bio else ''
            if len(bio) > self.MAX_BIO_LENGTH:
                raise ValueError(f"Bio deve ter no máximo {self.MAX_BIO_LENGTH} caracteres")
        
        
        # VALIDAÇÃO DA LOCALIZAÇÃO
        
        if request.location is not None:
            location = request.location.strip() if request.location else ''
            if len(location) > self.MAX_LOCATION_LENGTH:
                raise ValueError(f"Localização deve ter no máximo {self.MAX_LOCATION_LENGTH} caracteres")
        
        
        # VALIDAÇÃO DO WEBSITE
        
        if request.website is not None:
            website = request.website.strip() if request.website else None
            if len(website) > self.MAX_WEBSITE_LENGTH:
                raise ValueError(f"Website deve ter no máximo {self.MAX_WEBSITE_LENGTH} caracteres")
            
            # Validação básica de URL (opcional)
            if website and not website.startswith(('http://', 'https://')):
                website = f"https://{website}"
                # Poderia armazenar com https:// ou validar
                # raise ValueError("Website deve começar com http:// ou https://")
        
        
        # VALIDAÇÃO DOS ARQUIVOS
        
        if request.avatar:
            self._validate_file(request.avatar, "avatar", self.MAX_AVATAR_SIZE, self.MAX_AVATAR_GIF)
        if request.cover:
            self._validate_file(request.cover, "cover", self.MAX_COVER_SIZE, self.MAX_COVER_GIF)

    def _validate_file(self, file_data: Dict, file_type: str, max_size: int, max_gif_size: int):
        filename = file_data.get('filename', '')
        content_type = file_data.get('content_type', '')
        size = file_data.get('size', 0)
        extension = filename.split('.')[-1].lower() if filename else ''
        
        if content_type not in self.ALLOWED_MIME_TYPES or extension not in self.ALLOWED_EXTENSIONS:
            raise ValueError(f"Formato do {file_type} não suportado. Use JPG, PNG, GIF ou JFIF.")
        
        if content_type == 'image/gif' and size > max_gif_size:
            raise ValueError(f"GIF muito grande para {file_type}. Máximo: {max_gif_size // 1024 // 1024}MB.")
        
        if size > max_size:
            raise ValueError(f"{file_type.capitalize()} muito grande. Máximo: {max_size // 1024 // 1024}MB.")

    async def _process_avatar(self, request: UpdateProfileRequest):
        if request.avatar and request.avatar.get('data'):
            avatar_data = request.avatar
            is_gif = avatar_data['content_type'] == 'image/gif'
            image_bytes = avatar_data['data']
            
            converted = convert_to_webp(
                image_bytes,
                avatar_data['content_type'],
                ConvertOptions(
                    format='webp-animated' if is_gif else 'webp',
                    quality=75 if is_gif else 80,
                    width=512,
                    height=512,
                    fit='cover'
                )
            )
            
            filename = add_animated_suffix(f"avatar-{int(time.time())}.webp", is_gif)
            path = f"avatars/{request.user_id}/{filename}"
            url = await r2_client.upload_public(converted.buffer, path, 'image/webp')
            return url, path
        return None, None

    async def _process_cover(self, request: UpdateProfileRequest):
        if request.cover and request.cover.get('data'):
            cover_data = request.cover
            is_gif = cover_data['content_type'] == 'image/gif'
            image_bytes = cover_data['data']
            
            converted = convert_to_webp(
                image_bytes,
                cover_data['content_type'],
                ConvertOptions(
                    format='webp-animated' if is_gif else 'webp',
                    quality=75 if is_gif else 80,
                    width=1920,
                    height=400,
                    fit='cover'
                )
            )
            
            filename = add_animated_suffix(f"cover-{int(time.time())}.webp", is_gif)
            path = f"cover_image/{request.user_id}/{filename}"
            url = await r2_client.upload_public(converted.buffer, path, 'image/webp')
            return url, path
        return None, None

    async def _get_current_user(self, user_id: str):
        return await db.fetch_one(
            'SELECT id, avatar, "coverImage" FROM users WHERE id = $1 AND "deletedAt" IS NULL',
            user_id
        )

    async def _update_user(self, request: UpdateProfileRequest, new_avatar: str, new_cover: str):
        update_data = {
            'name': request.name.strip(),
            'username': request.username.lower().strip()
        }
        
        if request.bio is not None:
            update_data['bio'] = request.bio.strip() if request.bio else None
        
        if request.location is not None:
            update_data['location'] = request.location.strip() if request.location else None
        
        if request.website is not None:
            website = request.website.strip() if request.website else None
            if website and not website.startswith(('http://', 'https://')):
                website = f"https://{website}"
            update_data['website'] = website if website else None
        
        if new_avatar:
            update_data['avatar'] = new_avatar
        elif request.remove_avatar:
            update_data['avatar'] = None
        
        if new_cover:
            update_data['coverImage'] = new_cover
        elif request.remove_cover:
            update_data['coverImage'] = None

        set_clause = ', '.join([f'"{k}" = ${i+1}' for i, k in enumerate(update_data.keys())])
        values = list(update_data.values()) + [request.user_id]
        
        return await db.fetch_one(
            f'UPDATE users SET {set_clause}, "updatedAt" = CURRENT_TIMESTAMP WHERE id = ${len(values)} AND "deletedAt" IS NULL RETURNING *',
            *values
        )

    async def _cleanup_old_files(self, user: Dict, new_avatar: str, new_cover: str, rm_avatar: bool, rm_cover: bool):
        if user.get('avatar') and (new_avatar or rm_avatar):
            path = user['avatar'].split('.com/')[-1] if '.com/' in user['avatar'] else user['avatar']
            await r2_client.delete_file(path, is_public=True)
        
        if user.get('coverImage') and (new_cover or rm_cover):
            path = user['coverImage'].split('.com/')[-1] if '.com/' in user['coverImage'] else user['coverImage']
            await r2_client.delete_file(path, is_public=True)

    async def _rollback(self):
        if self._uploaded_avatar_path:
            await r2_client.delete_file(self._uploaded_avatar_path, is_public=True)
        if self._uploaded_cover_path:
            await r2_client.delete_file(self._uploaded_cover_path, is_public=True)