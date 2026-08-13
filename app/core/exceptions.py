class SetuHaulError(Exception):
    """Base exception for SetuHaul application errors."""


class NotFoundError(SetuHaulError):
    """Raised when a requested resource is not found."""
