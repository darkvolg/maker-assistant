"""Small, deterministic translations for the workbench workflow."""
from contextvars import ContextVar
from contextlib import contextmanager

_language = ContextVar("assistant_language", default="ru")


@contextmanager
def using_language(language):
    token = _language.set(language)
    try:
        yield
    finally:
        _language.reset(token)


def tr(ru, en):
    return en if _language.get() == "en" else ru
