from routers import questions, quiz

__all__ = ["questions", "quiz"]

try:
    from routers import generate
    __all__.append("generate")
except ImportError:
    pass
