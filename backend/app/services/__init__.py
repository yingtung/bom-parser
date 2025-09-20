from .document_ai import DocumentAIService

# Create a singleton instance
_document_ai_service = None


def get_document_ai_service() -> DocumentAIService:
    """Get the DocumentAIService singleton instance."""
    global _document_ai_service
    if _document_ai_service is None:
        _document_ai_service = DocumentAIService()
    return _document_ai_service


# For backward compatibility
document_ai_service = get_document_ai_service()
