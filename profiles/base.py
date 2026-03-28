from abc import ABC, abstractmethod
from typing import Any, Optional


class LanguageProfile(ABC):
    """
    Base class for language-specific configurations in Ariadne.
    Similar to a Neovim Lua config, but in Python.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The display name of the language (e.g., 'Rust')."""
        pass

    @property
    @abstractmethod
    def extensions(self) -> list[str]:
        """List of file extensions supported by this profile (e.g., ['.rs'])."""
        pass

    @abstractmethod
    def get_language_ptr(self) -> Any:
        """Return the tree-sitter language object/pointer."""
        pass

    @abstractmethod
    def get_query(self, symbol_name: str) -> str:
        """Return the Tree-sitter query string to find the target symbol."""
        pass

    @abstractmethod
    def get_skeleton_query(self) -> str:
        """Return the Tree-sitter query string to find bodies to strip for skeletonization."""
        pass

    @property
    @abstractmethod
    def target_capture_name(self) -> str:
        """The Tree-sitter capture name for target symbols (e.g., 'target')."""
        pass

    @property
    @abstractmethod
    def skeleton_capture_name(self) -> str:
        """The Tree-sitter capture name for skeletonized functions (e.g., 'func')."""
        pass

    @property
    @abstractmethod
    def test_generation_system_prompt(self) -> str:
        """The system prompt for generating language-specific unit tests."""
        pass

    @property
    @abstractmethod
    def search_system_prompt(self) -> str:
        """The system prompt for identifying missing symbols from errors."""
        pass

    @property
    @abstractmethod
    def coding_system_prompt(self) -> str:
        """The system prompt for generating the final code fix."""
        pass

    @abstractmethod
    def parse_search_result(self, response: str) -> Optional[str]:
        """
        Parse the LLM's raw response from the SEARCH state to extract
        the target function/item name.
        """
        pass

    @property
    def check_command(self) -> Optional[list[str]]:
        """The default build/lint command for this language."""
        return None
