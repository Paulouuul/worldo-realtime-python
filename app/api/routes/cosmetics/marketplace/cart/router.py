from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from app.auth.dependencies import get_current_user
from app.auth.schemas import UserInfo
from .add_item_use_case.use_case import AddItemUseCase, AddItemRequest
from .get_cart_use_case.use_case import GetCartUseCase, GetCartRequest
from .remove_item_use_case.use_case import RemoveItemUseCase, RemoveItemRequest
from .update_quantity_use_case.use_case import UpdateQuantityUseCase, UpdateQuantityRequest
from .clear_cart_use_case.use_case import ClearCartUseCase
from .validate_cart_use_case.use_case import ValidateCartUseCase, ValidateCartRequest
from .sync_cart_use_case.use_case import SyncCartUseCase, SyncCartRequest
from .get_item_quantity_use_case.use_case import GetItemQuantityUseCase, GetItemQuantityRequest
from fastapi.responses import JSONResponse

router = APIRouter()

class ItemCartSchema(BaseModel):
    listing_id: str
    frame_id: str
    name: str
    price: float
    seller_id: str
    seller_name: str
    quantity: int = 1
    max_quantity: int = 0
    image_url: Optional[str] = ""
    thumbnail_url: Optional[str] = ""

class AddToCartPayload(BaseModel):
    """Envelope esperado pelo frontend: { 'item_data': { ... } }"""
    item_data: ItemCartSchema

# ROTAS

@router.get("/get", summary="Obter meu próprio carrinho")
async def get_my_cart(
    user: Annotated[UserInfo, Depends(get_current_user)]
):
    """Retorna o carrinho do usuário autenticado"""
    
    request = GetCartRequest(user_id=user.id)
    response_data, status_code = await GetCartUseCase().execute(request)
    
    if "error" in response_data:
        return JSONResponse(
                status_code=status_code,
                content={"detail": response_data.get("error")}
        )
    
    return response_data


@router.get("/get/summary", summary="Obter resumo do meu carrinho")
async def get_my_cart_summary(
    user: Annotated[UserInfo, Depends(get_current_user)]
):
    """Retorna apenas o resumo do carrinho (totais quantitativos e financeiros)"""
    
    request = GetCartRequest(user_id=user.id)
    response_data, status_code = await GetCartUseCase().execute(request)
    
    if "error" in response_data:
        return JSONResponse(
                status_code=status_code,
                content={"detail": response_data.get("error")}
        )
    data = response_data.get("data", {})
    return {
        "total_items": data.get("total_items", 0),
        "total_price": data.get("total_price", 0),
        "unique_items_count": data.get("unique_items_count", 0)
    }
@router.get("/item/{listing_id}/quantity", summary="Obter quantidade de um item no carrinho")
async def get_item_quantity(
    listing_id: str,
    user: Annotated[UserInfo, Depends(get_current_user)]
):
    """
    Retorna a quantidade de um item específico no carrinho do usuário.
    Útil para saber quantas unidades de um listing já foram adicionadas.
    """
    request = GetItemQuantityRequest(user_id=user.id, listing_id=listing_id)
    response_data, status_code = await GetItemQuantityUseCase().execute(request)
    
    if "error" in response_data:
        return JSONResponse(
                status_code=status_code,
                content={"detail": response_data.get("error")}
        )
    
    return response_data


@router.post("/add/", summary="Adicionar item ao meu carrinho")
async def add_item_to_my_cart(
    user: Annotated[UserInfo, Depends(get_current_user)],
    payload: AddToCartPayload = Body(..., description="Dados do item envelopados em item_data")
):
    """Adiciona um item ao carrinho do usuário autenticado"""
    
    request = AddItemRequest(
        user_id=user.id,
        public_id=user.public_id,
        item_data=payload.item_data.model_dump()
    )
    response_data, status_code = await AddItemUseCase().execute(request)
    
    if "error" in response_data:
        return JSONResponse(
                status_code=status_code,
                content={"detail": response_data.get("error")}
        )
    
    return response_data


@router.delete("/remove/{item_id}", summary="Remover item do meu carrinho")
async def remove_item_from_my_cart(
    user: Annotated[UserInfo, Depends(get_current_user)],
    item_id: str
):
    """Remove um item específico do carrinho do usuário autenticado"""
    
    request = RemoveItemRequest(user_id=user.id, item_id=item_id)
    response_data, status_code = await RemoveItemUseCase().execute(request)
    
    if "error" in response_data:
        return JSONResponse(
                status_code=status_code,
                content={"detail": response_data.get("error")}
        )
    
    return response_data


@router.patch("/update/{item_id}", summary="Atualizar quantidade de item")
async def update_quantity_in_my_cart(
    user: Annotated[UserInfo, Depends(get_current_user)],
    item_id: str,
    quantity: int = Query(..., ge=0, description="Nova quantidade (0 remove o item)")
):
    """Atualiza a quantidade de um item no carrinho do usuário autenticado"""
    
    request = UpdateQuantityRequest(
        user_id=user.id,
        item_id=item_id,
        quantity=quantity
    )
    response_data, status_code = await UpdateQuantityUseCase().execute(request)
    
    if "error" in response_data:
        return JSONResponse(
                status_code=status_code,
                content={"detail": response_data.get("error")}
        )
    
    return response_data


@router.delete("/clear", summary="Esvaziar meu carrinho")
async def clear_my_cart(
    user: Annotated[UserInfo, Depends(get_current_user)]
):
    """Remove todos os itens do carrinho do usuário autenticado"""
    
    response_data, status_code = await ClearCartUseCase().execute(user.id)
    
    if "error" in response_data:
        return JSONResponse(
                status_code=status_code,
                content={"detail": response_data.get("error")}
        )
    
    return response_data


@router.post("/validate", summary="Validar carrinho para checkout")
async def validate_my_cart(
    user: Annotated[UserInfo, Depends(get_current_user)]
):
    """Valida o carrinho antes do checkout"""
    request = ValidateCartRequest(user_id=user.id)
    response_data, status_code = await ValidateCartUseCase().execute(request)
    
    if "error" in response_data:
        return JSONResponse(
                status_code=status_code,
                content={"detail": response_data.get("error")}
        )
    
    return response_data

# Sincronizar carrinho
@router.post("/sync", summary="Sincronizar carrinho com PostgreSQL")
async def sync_my_cart(
    user: Annotated[UserInfo, Depends(get_current_user)]
):
    """Força a sincronização do carrinho com PostgreSQL"""
    request = SyncCartRequest(user_id=user.id)
    response_data, status_code = await SyncCartUseCase().execute(request)
    
    if "error" in response_data:
        return JSONResponse(
                status_code=status_code,
                content={"detail": response_data.get("error")}
        )
    
    return response_data