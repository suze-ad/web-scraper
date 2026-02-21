"""
Pydantic Data Models.
Validates, serializes, and enforces structure on all scraped data.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


class ProductData(BaseModel):
    """Validated product data model."""

    name: str = Field(..., min_length=1, max_length=500, description="Product name")
    price: Optional[str] = Field(None, description="Price as displayed (e.g. '$19.99')")
    price_numeric: Optional[float] = Field(None, ge=0, description="Numeric price value")
    currency: Optional[str] = Field(None, max_length=10, description="Currency code or symbol")
    availability: str = Field(default="Unknown", description="Stock status")
    product_url: Optional[str] = Field(None, description="Product detail page URL")
    image_url: Optional[str] = Field(None, description="Product image URL")
    source_url: Optional[str] = Field(None, description="Page this product was scraped from")
    scraped_at: datetime = Field(default_factory=datetime.utcnow, description="Scrape timestamp")

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        """Strip and normalize whitespace in product name."""
        return " ".join(v.split()).strip()

    @field_validator("availability")
    @classmethod
    def normalize_availability(cls, v: str) -> str:
        """Normalize availability to standard values."""
        v_lower = v.lower().strip()
        if any(kw in v_lower for kw in ["in stock", "in-stock", "available"]):
            return "In Stock"
        elif any(kw in v_lower for kw in ["out of stock", "sold out", "unavailable", "out-of-stock"]):
            return "Out of Stock"
        elif any(kw in v_lower for kw in ["pre-order", "preorder", "coming soon"]):
            return "Pre-Order"
        elif any(kw in v_lower for kw in ["limited", "few left", "low stock"]):
            return "Limited Stock"
        return v if v else "Unknown"

    @field_validator("product_url", "image_url", mode="before")
    @classmethod
    def validate_url(cls, v: Optional[str]) -> Optional[str]:
        """Basic URL validation."""
        if v is None or v.strip() == "":
            return None
        v = v.strip()
        if v.startswith("//"):
            v = "https:" + v
        if not v.startswith(("http://", "https://")):
            return None
        return v

    model_config = {"str_strip_whitespace": True}


class ScrapingResult(BaseModel):
    """Complete result of a scraping job."""

    job_id: str = Field(..., description="Unique job identifier")
    url: str = Field(..., description="Target URL that was scraped")
    site_type: str = Field(default="unknown", description="Detected site type (static/dynamic)")
    engine_used: str = Field(default="unknown", description="Scraping engine used")
    pages_scraped: int = Field(default=0, ge=0, description="Number of pages scraped")
    products_found: int = Field(default=0, ge=0, description="Total products found (before cleaning)")
    products_cleaned: int = Field(default=0, ge=0, description="Products after cleaning/dedup")
    products: List[ProductData] = Field(default_factory=list, description="List of product data")
    errors: List[str] = Field(default_factory=list, description="Errors encountered during scraping")
    warnings: List[str] = Field(default_factory=list, description="Warnings during scraping")
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    success: bool = Field(default=False)

    def finalize(self) -> None:
        """Mark the job as complete and calculate duration."""
        self.completed_at = datetime.utcnow()
        self.duration_seconds = (self.completed_at - self.started_at).total_seconds()
        self.products_cleaned = len(self.products)
        self.success = len(self.products) > 0


class ProxyConfig(BaseModel):
    """Proxy configuration model."""

    url: str = Field(..., description="Proxy URL (http://host:port)")
    username: Optional[str] = None
    password: Optional[str] = None
    protocol: str = Field(default="http", description="http or socks5")

    @property
    def full_url(self) -> str:
        if self.username and self.password:
            # Extract protocol and host
            proto, rest = self.url.split("://", 1)
            return f"{proto}://{self.username}:{self.password}@{rest}"
        return self.url

    @property
    def as_dict(self) -> dict:
        proxy_url = self.full_url
        return {"http": proxy_url, "https": proxy_url}
