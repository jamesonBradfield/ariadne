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
    def skeleton_capture_name(self) -> str:
        """The Tree-sitter capture name for skeletonized functions (e.g., 'func')."""
        pass

    @property
    @abstractmethod
    def test_generation_system_prompt(self) -> str:
        """The system prompt for generating language-specific unit tests."""
        pass

    @abstractmethod
    def parse_search_result(self, response: str) -> Optional[str]:
        """
        Parse the LLM's raw response from the SEARCH state to extract
        the target function/item name.
        """
        pass

    @property
    @abstractmethod
    def target_capture_name(self) -> str:
        """The Tree-sitter capture name for target symbols (e.g., 'function')."""
        pass

    @property
    @abstractmethod
    def coding_example(self) -> str:
        """Language-specific JSON example for the coding prompt."""
        pass

    @property
    def coding_system_prompt(self) -> str:
        """The system prompt for generating multi-symbol code fixes in JSON format."""
        return (
            f"You are an expert {self.name} developer and an automated surgical execution engine.\n"
            "You MUST output ONLY a SINGLE valid JSON object. No markdown formatting, no conversational text, no explanations, and NO trailing commas.\n"
            "The JSON object MUST contain exactly one key called 'edits', which is an array of objects.\n"
            "Each object in the array MUST contain 'symbol' and 'new_code'.\n"
            "Example Expected Output:\n"
            f"{self.coding_example}"
        )

    @property
    def check_command(self) -> Optional[list[str]]:
        """The default build/lint command for this language."""
        return None
