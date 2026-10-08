class PromptXError(RuntimeError):
    """An expected, user-facing PromptX failure."""


class ConfigError(PromptXError):
    """Configuration is missing or invalid."""


class BackendError(PromptXError):
    """An external backend failed."""
