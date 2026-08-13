class SetuHaulError(Exception):
    """Base exception for SetuHaul application errors."""


class NotFoundError(SetuHaulError):
    """Raised when a requested resource is not found."""


class ConflictError(SetuHaulError):
    """Raised when an allocation or resource conflict prevents the operation."""
