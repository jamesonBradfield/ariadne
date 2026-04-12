from typing import Any, Dict, List, Optional


def get_lsp_manager(config_manager, job=None):
    from .lsp import LSPService
    from ..core import EngineContext

    if job and hasattr(job, "lsp_service"):
        return job.lsp_service

    if not hasattr(config_manager, "_lsp_service"):
        config_manager._lsp_service = LSPService()

    return config_manager._lsp_service
