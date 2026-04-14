"""
CLI entry point.

Registered as ``saintbot-cli`` via pyproject.toml.

Usage:
    saintbot-cli              # launch the interactive main menu
    saintbot-cli setup        # re-run first-time setup
    saintbot-cli setup --reset  # delete config + DB and re-run setup
"""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import click
from rich import print as rprint

from crypto_trading_cli import __version__
from crypto_trading_cli.config import (
    CONFIG_DIR,
    CONFIG_PATH,
    AppConfig,
    load_config,
    save_config,
)
from crypto_trading_cli.db import init_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Click group
# ---------------------------------------------------------------------------


@click.group(invoke_without_command=True)
@click.version_option(__version__, prog_name="crypto-cli")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """crypto-cli — manage local Freqtrade crypto trading bots."""
    if ctx.invoked_subcommand is None:
        _run(interactive=True)


# ---------------------------------------------------------------------------
# setup command
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--reset",
    is_flag=True,
    default=False,
    help="Delete existing config and database, then re-run setup.",
)
@click.option(
    "--proxy",
    default="",
    metavar="URL",
    help="Set or update the proxy URL (e.g. http://127.0.0.1:7890).",
)
def setup(reset: bool, proxy: str) -> None:
    """Run first-time setup (or reset an existing installation)."""
    if reset:
        _do_reset()
        _run_setup(proxy_url=proxy)
        return

    # If only --proxy is given, update the proxy in an existing config
    if proxy and not reset:
        cfg = load_config()
        if cfg:
            cfg.proxy_url = proxy
            save_config(cfg)
            rprint(f"[green]✓ Proxy updated:[/green] {proxy}")
            return

    _run_setup(proxy_url=proxy)


@cli.command()
@click.argument("proxy_url", required=False, default=None)
def proxy(proxy_url: str | None) -> None:
    """
    View or update the proxy setting.

    \b
    Examples:
      crypto-cli proxy                           # show current proxy
      crypto-cli proxy http://127.0.0.1:7890    # set HTTP proxy
      crypto-cli proxy socks5://127.0.0.1:1080  # set SOCKS5 proxy
      crypto-cli proxy clear                     # remove proxy (direct connection)
    """
    cfg = load_config()
    if cfg is None:
        rprint("[red]Not set up yet. Run 'crypto-cli' first.[/red]")
        raise SystemExit(1)

    # No argument — show current value
    if proxy_url is None:
        current = cfg.proxy_url or "(none — direct connection)"
        rprint(f"Current proxy: [cyan]{current}[/cyan]")
        rprint("\nTo set:   [dim]crypto-cli proxy http://127.0.0.1:7890[/dim]")
        rprint("To clear: [dim]crypto-cli proxy clear[/dim]")
        return

    # "clear" keyword removes the proxy
    if proxy_url.lower() == "clear":
        cfg.proxy_url = ""
        save_config(cfg)
        rprint("[green]✓ Proxy cleared — using direct connection.[/green]")
        return

    cfg.proxy_url = proxy_url.strip()
    save_config(cfg)
    rprint(f"[green]✓ Proxy set to:[/green] {cfg.proxy_url}")


# ---------------------------------------------------------------------------
# Main entry logic
# ---------------------------------------------------------------------------


def _run(interactive: bool = True) -> None:
    """
    Load config (or run setup if missing), then launch the main menu.
    """
    try:
        cfg = load_config()
    except ValueError as exc:
        rprint(f"[red]Config file is corrupted: {exc}[/red]")
        rprint("[dim]Running setup again...[/dim]")
        cfg = None

    if cfg is None:
        cfg = _run_setup()

    # Initialise DB
    try:
        init_db(cfg.db_path)
    except Exception as exc:
        rprint(f"[red]Database error: {exc}[/red]")
        rprint("[dim]Run 'crypto-cli setup --reset' to reinitialise.[/dim]")
        sys.exit(1)

    # Initialise BotManager and recover any previously-running bots
    from crypto_trading_cli.bot_manager import init_bot_manager
    manager = init_bot_manager(cfg.freqtrade_bin, proxy_url=cfg.proxy_url)
    manager.recover_on_startup()

    if interactive:
        from crypto_trading_cli.ui.menus import run_main_menu
        try:
            run_main_menu(manager)
        except SystemExit:
            raise
        except KeyboardInterrupt:
            rprint("\n[dim]Goodbye![/dim]")
            sys.exit(0)
        except Exception as exc:
            rprint(f"[red]Unexpected error: {exc}[/red]")
            logger.debug("Unhandled exception", exc_info=True)
            sys.exit(1)


# ---------------------------------------------------------------------------
# First-run setup
# ---------------------------------------------------------------------------


def _run_setup(proxy_url: str = "") -> AppConfig:
    """
    Detect the freqtrade binary, create ~/.crypto-cli/, and write config.json.

    Returns the newly created AppConfig.
    Exits with code 1 if freqtrade is not found.
    """
    rprint("\n[bold cyan]crypto-cli — First-time Setup[/bold cyan]")
    rprint("[dim]Checking for Freqtrade installation...[/dim]\n")

    ft_bin = _find_freqtrade()
    if ft_bin is None:
        rprint("[red]Freqtrade not found.[/red]")
        rprint(
            "Please install Freqtrade first:\n"
            "  [link=https://www.freqtrade.io/en/stable/installation/]"
            "https://www.freqtrade.io/en/stable/installation/[/link]"
        )
        sys.exit(1)

    ft_version = _get_freqtrade_version(ft_bin)
    rprint(f"[green]✓ Found Freqtrade:[/green] {ft_bin}  ({ft_version})")

    # Proxy configuration
    if not proxy_url:
        rprint("\n[bold]Proxy configuration[/bold]")
        rprint("[dim]If you are in a region that requires a proxy to access exchanges,")
        rprint("enter the proxy URL now (e.g. http://127.0.0.1:7890 or socks5://127.0.0.1:1080).")
        rprint("Press Enter to skip.[/dim]")
        proxy_url = input("Proxy URL (optional): ").strip()

    if proxy_url:
        rprint(f"[green]✓ Proxy configured:[/green] {proxy_url}")
    else:
        rprint("[dim]No proxy configured.[/dim]")

    # Create config dir and write config
    db_path = str(CONFIG_DIR / "bots.db")
    from datetime import datetime, timezone
    cfg = AppConfig(
        freqtrade_bin=ft_bin,
        freqtrade_version=ft_version,
        db_path=db_path,
        proxy_url=proxy_url,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    save_config(cfg)
    rprint(f"[green]✓ Config saved to:[/green] {CONFIG_PATH}")

    # Initialise DB
    init_db(db_path)
    rprint(f"[green]✓ Database initialised at:[/green] {db_path}")
    rprint("\n[bold green]Setup complete! Launching main menu...[/bold green]\n")

    return cfg


def _find_freqtrade() -> str | None:
    """
    Search for the freqtrade binary in common locations and PATH.

    Returns the absolute path if found, None otherwise.
    """
    candidates = [
        str(Path.home() / ".local" / "bin" / "freqtrade"),
        "/usr/local/bin/freqtrade",
        "/usr/bin/freqtrade",
    ]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    # Check PATH
    found = shutil.which("freqtrade")
    return found


def _get_freqtrade_version(ft_bin: str) -> str:
    """Return the version string from ``freqtrade --version``."""
    try:
        result = subprocess.run(
            [ft_bin, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() or result.stderr.strip() or "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


def _do_reset() -> None:
    """Delete config.json and bots.db after user confirmation."""
    from crypto_trading_cli.ui.prompts import confirm as ui_confirm

    rprint("[yellow]This will delete your config and all bot records.[/yellow]")
    if not ui_confirm("Are you sure you want to reset?", default=False):
        rprint("[dim]Reset cancelled.[/dim]")
        sys.exit(0)

    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()
        rprint(f"[red]Deleted:[/red] {CONFIG_PATH}")

    db_path = CONFIG_DIR / "bots.db"
    if db_path.exists():
        db_path.unlink()
        rprint(f"[red]Deleted:[/red] {db_path}")

    rprint("[dim]Reset complete. Running setup...[/dim]\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Wrapper that catches top-level exceptions for clean error display."""
    try:
        cli(standalone_mode=False)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        rprint("\n[dim]Goodbye![/dim]")
        sys.exit(0)
    except Exception as exc:
        rprint(f"[red]Unexpected error: {exc}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
