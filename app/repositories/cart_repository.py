# app/repositories/cart_repository.py
from app.core.redis_client import redis_client
from app.entities.cart_entity import CartEntity
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class CartRepository:
    """
    Repository para persistência do carrinho no Redis
    
    Responsabilidades:
    - Salvar carrinho no Redis
    - Buscar carrinho pelo ID do usuário
    - Deletar carrinho
    - Verificar existência
    """
    
    # Prefixo para as chaves do Redis
    PREFIX = "cart:"
    
    # Tempo de vida em segundos (7 dias)
    TTL = 604800
    
    def _get_key(self, user_id: str) -> str:
        """Gera a chave do Redis para o usuário"""
        return f"{self.PREFIX}{user_id}"
    
    def save(self, cart: CartEntity) -> bool:
        """
        Salva o carrinho no Redis
        
        Args:
            cart: Entidade do carrinho
            
        Returns:
            bool: True se salvou com sucesso
        """
        try:
            key = self._get_key(cart.user_id)
            data = cart.to_dict()  # Usa o método da EntityInterface
            
            success = redis_client.set_json(key, data, self.TTL)
            
            if success:
                logger.info(f"Carrinho salvo para usuário: {cart.user_id}")
            else:
                logger.error(f"Falha ao salvar carrinho: {cart.user_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Erro ao salvar carrinho: {e}")
            return False
    
    def find_by_user_id(self, user_id: str) -> Optional[CartEntity]:
        """
        Busca carrinho pelo ID do usuário
        
        Args:
            user_id: ID do usuário
            
        Returns:
            CartEntity | None: Carrinho encontrado ou None
        """
        try:
            key = self._get_key(user_id)
            data = redis_client.get_json(key)
            
            if not data:
                logger.info(f"Carrinho não encontrado para usuário: {user_id}")
                return None
            
            # Reconstrói a entidade usando from_dict
            cart = CartEntity.from_dict(data)
            logger.info(f"Carrinho carregado para usuário: {user_id}")
            
            return cart
            
        except Exception as e:
            logger.error(f"Erro ao buscar carrinho: {e}")
            return None
    
    def delete(self, user_id: str) -> bool:
        """
        Remove o carrinho do Redis
        
        Args:
            user_id: ID do usuário
            
        Returns:
            bool: True se deletou com sucesso
        """
        try:
            key = self._get_key(user_id)
            result = redis_client.delete(key)
            
            if result:
                logger.info(f"Carrinho deletado para usuário: {user_id}")
            else:
                logger.info(f"Carrinho não existia para deletar: {user_id}")
            
            return result > 0
            
        except Exception as e:
            logger.error(f"Erro ao deletar carrinho: {e}")
            return False
    
    def exists(self, user_id: str) -> bool:
        """
        Verifica se o carrinho existe
        
        Args:
            user_id: ID do usuário
            
        Returns:
            bool: True se o carrinho existe
        """
        try:
            key = self._get_key(user_id)
            return redis_client.exists(key)
            
        except Exception as e:
            logger.error(f"Erro ao verificar carrinho: {e}")
            return False
    
    def get_ttl(self, user_id: str) -> int:
        """
        Retorna o tempo de vida restante do carrinho em segundos
        
        Args:
            user_id: ID do usuário
            
        Returns:
            int: TTL em segundos (-1 se não expira, -2 se não existe)
        """
        try:
            key = self._get_key(user_id)
            return redis_client.client.ttl(key)
        except Exception as e:
            logger.error(f"Erro ao obter TTL: {e}")
            return -2