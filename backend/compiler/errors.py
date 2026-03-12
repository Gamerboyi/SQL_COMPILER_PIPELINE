"""
Custom error classes for the SQL compiler pipeline.
Each error captures position information for frontend highlighting.
"""


class CompilerError(Exception):
    """Base class for all compiler errors."""

    def __init__(self, message, line=None, col=None, stage=None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col
        self.stage = stage

    def to_dict(self):
        return {
            "message": self.message,
            "line": self.line,
            "col": self.col,
            "stage": self.stage,
            "severity": "error"
        }


class LexerError(CompilerError):
    """Error during tokenization."""

    def __init__(self, message, line=None, col=None):
        super().__init__(message, line, col, stage="lexer")


class ParserError(CompilerError):
    """Error during parsing (syntax error)."""

    def __init__(self, message, line=None, col=None):
        super().__init__(message, line, col, stage="parser")


class SemanticError(CompilerError):
    """Error during semantic analysis."""

    def __init__(self, message, line=None, col=None):
        super().__init__(message, line, col, stage="semantic")


class SemanticWarning:
    """Warning during semantic analysis (non-fatal)."""

    def __init__(self, message, line=None, col=None):
        self.message = message
        self.line = line
        self.col = col
        self.stage = "semantic"

    def to_dict(self):
        return {
            "message": self.message,
            "line": self.line,
            "col": self.col,
            "stage": self.stage,
            "severity": "warning"
        }
