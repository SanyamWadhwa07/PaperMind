"""Pydantic models for FastAPI request/response validation."""

from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, Any
import re


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator('email')
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = None

    @field_validator('email')
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator('full_name')
    @classmethod
    def strip_name(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class PasswordResetRequest(BaseModel):
    email: str

    @field_validator('email')
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()


class PasswordResetConfirmRequest(BaseModel):
    token: str
    new_password: str

    @field_validator('token')
    @classmethod
    def require_token(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError('token is required')
        return v


class ArxivSearchRequest(BaseModel):
    """Search arXiv by free-text query."""

    query: str
    max_results: int = 10

    @field_validator('query')
    @classmethod
    def validate_query(cls, v: str) -> str:
        v = v.strip()[:300]
        if not v:
            raise ValueError('query is required')
        return v

    @field_validator('max_results')
    @classmethod
    def cap_results(cls, v: int) -> int:
        return min(max(v, 1), 50)


class ProfileUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None


class ArxivProcessRequest(BaseModel):
    arxiv_id: str
    primary_category: Optional[str] = None

    @field_validator('arxiv_id')
    @classmethod
    def validate_arxiv_id(cls, v: str) -> str:
        v = v.strip()
        match = re.search(r'(\d{4}\.\d{4,5}(?:v\d+)?)', v)
        if not match:
            raise ValueError('Invalid arXiv ID format. Expected e.g. 2311.12345 or 2311.12345v2')
        return match.group(1)


class FeedbackRequest(BaseModel):
    rating: Optional[int] = None
    comment: Optional[str] = None
    feedback_type: str = 'rating'

    @field_validator('rating')
    @classmethod
    def validate_rating(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 5):
            raise ValueError('rating must be between 1 and 5')
        return v

    @field_validator('comment')
    @classmethod
    def cap_comment(cls, v: Optional[str]) -> Optional[str]:
        return v[:1000] if v else None


class CollectionCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    color: str = '#6366f1'

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()[:255]
        if not v:
            raise ValueError('name is required')
        return v

    @field_validator('color')
    @classmethod
    def validate_color(cls, v: str) -> str:
        if not re.match(r'^#[0-9a-fA-F]{6}$', v):
            return '#6366f1'
        return v


class AddPaperToCollectionRequest(BaseModel):
    summary_id: str


class BatchCompareRequest(BaseModel):
    summary_ids: list[str]

    @field_validator('summary_ids')
    @classmethod
    def validate_ids(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError('Provide at least 2 summary IDs')
        if len(v) > 10:
            raise ValueError('Maximum 10 papers per comparison')
        return v


class SemanticSearchRequest(BaseModel):
    query: str
    top_k: int = 10

    @field_validator('query')
    @classmethod
    def cap_query(cls, v: str) -> str:
        return v[:500]

    @field_validator('top_k')
    @classmethod
    def cap_top_k(cls, v: int) -> int:
        return min(max(v, 1), 50)
