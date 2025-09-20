from typing import Optional

from sqlmodel import Field, SQLModel


class ItemBase(SQLModel):
    """Base model for Item with common fields."""

    title: str = Field(index=True)
    description: Optional[str] = Field(default=None, index=True)


class Item(ItemBase, table=True):
    """Item model for database table."""

    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id")


class ItemCreate(ItemBase):
    """Item creation model."""

    pass


class ItemUpdate(SQLModel):
    """Item update model."""

    title: Optional[str] = None
    description: Optional[str] = None


class ItemRead(ItemBase):
    """Item read model."""

    id: int
    owner_id: int
