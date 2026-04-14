"""
Rich table and panel renderers for the CLI UI.

All output uses the ``rich`` library for formatted, colour-coded terminal output.
"""

from typing import Any

from rich import print as rprint
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from crypto_trading_cli.db import BotRecord

# ---------------------------------------------------------------------------
# Status colour mapping
# ---------------------------------------------------------------------------

STATUS_COLORS: dict[str, str] = {
    "running": "green",
    "stopped": "yellow",
    "error": "red",
}


def _status_text(status: str) -> Text:
    """Return a coloured rich Text object for a bot status string."""
    color = STATUS_COLORS.get(status, "white")
    return Text(status, style=color)


# ---------------------------------------------------------------------------
# Bot list table
# ---------------------------------------------------------------------------


def render_bot_list(bots: list[BotRecord]) -> None:
    """
    Print a formatted table of all bots.

    Columns: #, Bot ID (8 chars), Status, Strategy, Exchange, Dry-run, Created At

    If *bots* is empty, prints "No bots found." instead.
    """
    if not bots:
        rprint("[dim]No bots found.[/dim]")
        return

    table = Table(
        title="Your Bots",
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Bot ID", width=10)
    table.add_column("Status", width=10)
    table.add_column("Strategy", width=10)
    table.add_column("Exchange", width=18)
    table.add_column("Dry-run", width=8, justify="center")
    table.add_column("Created At", width=22)

    for i, bot in enumerate(bots, start=1):
        table.add_row(
            str(i),
            bot.id[:8],
            _status_text(bot.status),
            bot.strategy.upper(),
            bot.exchange,
            "✓" if bot.dry_run else "✗",
            bot.created_at[:19].replace("T", " "),
        )

    rprint(table)


# ---------------------------------------------------------------------------
# Single bot status panel
# ---------------------------------------------------------------------------


def render_bot_status(bot: BotRecord, health: dict[str, Any] | None = None, ft_password: str | None = None) -> None:
    """
    Print a detail panel for a single bot.

    Args:
        bot:         The bot record to display.
        health:      Optional health dict from ``BotManager.get_health()``.
        ft_password: Optional decrypted Freqtrade Web UI password to display.
    """
    color = STATUS_COLORS.get(bot.status, "white")
    lines = [
        f"[bold]Bot ID:[/bold]    {bot.id[:8]}",
        f"[bold]Status:[/bold]    [{color}]{bot.status}[/{color}]",
        f"[bold]Strategy:[/bold]  {bot.strategy.upper()}",
        f"[bold]Exchange:[/bold]  {bot.exchange}",
        f"[bold]Dry-run:[/bold]   {'Yes' if bot.dry_run else 'No'}",
        f"[bold]Sandbox:[/bold]   {'Yes' if bot.sandbox else 'No'}",
        f"[bold]Port:[/bold]      {bot.port or '—'}",
        f"[bold]Created:[/bold]   {bot.created_at[:19].replace('T', ' ')}",
    ]

    if bot.port:
        lines.append(f"[bold]Web UI:[/bold]    http://127.0.0.1:{bot.port}")
        lines.append(f"[bold]Username:[/bold]  freqtrade")
        if ft_password:
            lines.append(f"[bold]Password:[/bold]  {ft_password}")
        else:
            lines.append(f"[bold]Password:[/bold]  [dim](unavailable)[/dim]")

    if health:
        lines.append("")
        lines.append("[bold]Health:[/bold]")
        api_ok = health.get("api_reachable", False)
        lines.append(f"  API reachable: {'[green]Yes[/green]' if api_ok else '[red]No[/red]'}")
        if health.get("last_process_ts"):
            lines.append(f"  Last process:  {health['last_process_ts']}")

    if bot.error_msg:
        lines.append("")
        lines.append(f"[bold red]Error:[/bold red] {bot.error_msg}")

    rprint(Panel("\n".join(lines), title="Bot Status", border_style="cyan"))


# ---------------------------------------------------------------------------
# Open trades table
# ---------------------------------------------------------------------------


def render_trades_table(trades: list[dict[str, Any]]) -> None:
    """
    Print a table of open trades.

    Columns: Trade ID, Pair, Open Rate, Current Rate, Profit %, Open Date
    """
    if not trades:
        rprint("[dim]No open trades.[/dim]")
        return

    table = Table(
        title="Open Trades",
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
    )
    table.add_column("Trade ID", width=10, justify="right")
    table.add_column("Pair", width=12)
    table.add_column("Open Rate", width=14, justify="right")
    table.add_column("Current Rate", width=14, justify="right")
    table.add_column("Profit %", width=10, justify="right")
    table.add_column("Open Date", width=22)

    for trade in trades:
        profit_pct = trade.get("profit_pct", trade.get("profit_ratio", 0.0))
        if isinstance(profit_pct, float):
            profit_pct_display = f"{profit_pct * 100:.2f}%"
            profit_color = "green" if profit_pct >= 0 else "red"
        else:
            profit_pct_display = str(profit_pct)
            profit_color = "white"

        table.add_row(
            str(trade.get("trade_id", "—")),
            str(trade.get("pair", "—")),
            f"{trade.get('open_rate', 0.0):.6f}",
            f"{trade.get('current_rate', 0.0):.6f}",
            Text(profit_pct_display, style=profit_color),
            str(trade.get("open_date", "—"))[:19],
        )

    rprint(table)


# ---------------------------------------------------------------------------
# Profit summary panel
# ---------------------------------------------------------------------------


def render_profit(data: dict[str, Any]) -> None:
    """
    Print a profit summary panel.

    Args:
        data: Dict with keys ``profit_total``, ``profit_realized``, ``trade_count``.
    """
    total = data.get("profit_total", 0.0)
    realized = data.get("profit_realized", 0.0)
    count = data.get("trade_count", 0)

    total_color = "green" if total >= 0 else "red"
    realized_color = "green" if realized >= 0 else "red"

    lines = [
        f"[bold]Total Profit:[/bold]    [{total_color}]{total:.2f}%[/{total_color}]",
        f"[bold]Realised Profit:[/bold] [{realized_color}]{realized:.2f}%[/{realized_color}]",
        f"[bold]Total Trades:[/bold]    {count}",
    ]

    rprint(Panel("\n".join(lines), title="Profit Summary", border_style="cyan"))
