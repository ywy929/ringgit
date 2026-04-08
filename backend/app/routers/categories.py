from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Category, KeywordMapping
from app.schemas import CategoryCreate, CategoryResponse, KeywordMappingResponse

router = APIRouter()


@router.get("/api/categories", response_model=list[CategoryResponse])
def list_categories(db: Session = Depends(get_db)):
    return db.query(Category).order_by(Category.name).all()


@router.post("/api/categories", response_model=CategoryResponse)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db)):
    cat = Category(name=payload.name, is_default=False)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.patch("/api/categories/{cat_id}", response_model=CategoryResponse)
def rename_category(cat_id: int, payload: CategoryCreate, db: Session = Depends(get_db)):
    cat = db.query(Category).get(cat_id)
    cat.name = payload.name
    db.commit()
    db.refresh(cat)
    return cat


@router.get("/api/keyword-mappings", response_model=list[KeywordMappingResponse])
def list_keyword_mappings(db: Session = Depends(get_db)):
    mappings = db.query(KeywordMapping).all()
    results = []
    for m in mappings:
        results.append(KeywordMappingResponse(
            id=m.id,
            keyword_pattern=m.keyword_pattern,
            category_id=m.category_id,
            category_name=m.category.name if m.category else None,
            source=m.source,
        ))
    return results


@router.delete("/api/keyword-mappings/{mapping_id}")
def delete_keyword_mapping(mapping_id: int, db: Session = Depends(get_db)):
    mapping = db.query(KeywordMapping).get(mapping_id)
    if not mapping:
        return {"detail": "Not found"}
    db.delete(mapping)
    db.commit()
    return {"detail": "Deleted"}
