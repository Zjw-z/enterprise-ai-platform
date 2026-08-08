"""Knowledge-domain exceptions used across service and worker seams."""


class KnowledgeParsingLeaseLostError(RuntimeError):
    """Raised when a parsing worker no longer owns the document lease."""
