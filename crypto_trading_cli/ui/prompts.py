"""
Interactive prompt helpers.

Provides masked input (for API credentials), numbered selection menus,
confirmation prompts, and typed input with re-prompting on invalid values.
"""

from typing import Optional, TypeVar

from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from rich import print as rprint

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Masked input (for API keys / secrets)
# ---------------------------------------------------------------------------

_MASK_STYLE = Style.from_dict({"": "#ansiyellow"})


def masked_input(label: str, required: bool = True) -> str:
    """
    Prompt for a secret value with masked input (characters shown as ``*``).

    If *required* is True (default), re-prompts on empty input.
    If *required* is False, returns an empty string when the user presses Enter.

    Args:
        label:    The prompt label shown to the user (e.g. "API Key").
        required: Whether a non-empty value is mandatory.

    Returns:
        The entered string (stripped of leading/trailing whitespace).
    """
    while True:
        value = pt_prompt(
            HTML(f"<b>{label}:</b> "),
            is_password=True,
        ).strip()
        if value:
            return value
        if not required:
            return ""
        rprint("[red]This field is required. Please enter a value.[/red]")


# ---------------------------------------------------------------------------
# Numbered selection
# ---------------------------------------------------------------------------


def select_from_list(
    items: list[str],
    title: str = "Select an option",
    allow_cancel: bool = True,
) -> Optional[int]:
    """
    Display a numbered list and return the 0-based index of the selected item.

    Args:
        items:        List of option strings to display.
        title:        Header text shown above the list.
        allow_cancel: If True, option 0 cancels and returns None.

    Returns:
        0-based index of the selected item, or None if the user cancelled.
    """
    rprint(f"\n[bold cyan]{title}[/bold cyan]")
    for i, item in enumerate(items, start=1):
        rprint(f"  [bold]{i}.[/bold] {item}")
    if allow_cancel:
        rprint("  [bold]0.[/bold] Cancel")

    while True:
        raw = input("\nSelect: ").strip()
        if not raw.isdigit():
            rprint("[red]Invalid input: please enter a number.[/red]")
            continue
        choice = int(raw)
        if allow_cancel and choice == 0:
            return None
        if 1 <= choice <= len(items):
            return choice - 1  # 0-based index
        rprint(f"[red]Invalid selection. Enter a number between 1 and {len(items)}.[/red]")


# ---------------------------------------------------------------------------
# Confirmation prompt
# ---------------------------------------------------------------------------


def confirm(message: str, default: bool = False) -> bool:
    """
    Ask a yes/no confirmation question.

    Args:
        message: The question to display.
        default: Default answer if the user presses Enter without typing.
                 True = default Yes, False = default No.

    Returns:
        True if the user confirmed, False otherwise.
    """
    hint = "[Y/n]" if default else "[y/N]"
    while True:
        raw = input(f"{message} {hint}: ").strip().lower()
        if raw == "":
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        rprint("[red]Please enter 'y' or 'n'.[/red]")


# ---------------------------------------------------------------------------
# Typed input helpers
# ---------------------------------------------------------------------------


def prompt_str(label: str, default: str = "") -> str:
    """
    Prompt for a non-empty string value.

    Re-prompts if the user submits an empty string and no default is set.
    """
    hint = f" [{default}]" if default else ""
    while True:
        raw = input(f"{label}{hint}: ").strip()
        if raw:
            return raw
        if default:
            return default
        rprint("[red]This field is required.[/red]")


def prompt_int(
    label: str,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
    default: Optional[int] = None,
) -> int:
    """
    Prompt for an integer value with optional range validation.

    Re-prompts on non-integer input or out-of-range values.
    """
    hint_parts = []
    if min_value is not None and max_value is not None:
        hint_parts.append(f"{min_value}–{max_value}")
    elif min_value is not None:
        hint_parts.append(f"≥ {min_value}")
    elif max_value is not None:
        hint_parts.append(f"≤ {max_value}")
    if default is not None:
        hint_parts.append(f"default: {default}")
    hint = f" ({', '.join(hint_parts)})" if hint_parts else ""

    while True:
        raw = input(f"{label}{hint}: ").strip()
        if raw == "" and default is not None:
            return default
        try:
            value = int(raw)
        except ValueError:
            rprint("[red]Invalid input: expected a number.[/red]")
            continue
        if min_value is not None and value < min_value:
            rprint(f"[red]Value must be ≥ {min_value}.[/red]")
            continue
        if max_value is not None and value > max_value:
            rprint(f"[red]Value must be ≤ {max_value}.[/red]")
            continue
        return value


def prompt_float(
    label: str,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    default: Optional[float] = None,
) -> float:
    """
    Prompt for a float value with optional range validation.

    Re-prompts on non-numeric input or out-of-range values.
    """
    hint_parts = []
    if min_value is not None:
        hint_parts.append(f"≥ {min_value}")
    if max_value is not None:
        hint_parts.append(f"≤ {max_value}")
    if default is not None:
        hint_parts.append(f"default: {default}")
    hint = f" ({', '.join(hint_parts)})" if hint_parts else ""

    while True:
        raw = input(f"{label}{hint}: ").strip()
        if raw == "" and default is not None:
            return default
        try:
            value = float(raw)
            if not (value == value) or value == float("inf") or value == float("-inf"):
                raise ValueError("not a finite number")
        except ValueError:
            rprint("[red]Invalid input: expected a number.[/red]")
            continue
        if min_value is not None and value < min_value:
            rprint(f"[red]Value must be ≥ {min_value}.[/red]")
            continue
        if max_value is not None and value > max_value:
            rprint(f"[red]Value must be ≤ {max_value}.[/red]")
            continue
        return value
