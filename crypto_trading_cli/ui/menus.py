"""
Interactive menu flows for the CLI.

All user interaction is handled here. Each flow collects input, calls
BotManager, and displays results using the tables/prompts helpers.
"""

import logging
from typing import Optional

from rich import print as rprint
from rich.panel import Panel

from crypto_trading_cli.bot_manager import BotManager, CreateBotParams
from crypto_trading_cli.exchange import (
    EXCHANGE_DISPLAY_NAMES,
    EXCHANGES_REQUIRING_PASSPHRASE,
    SUPPORTED_EXCHANGES,
)
from crypto_trading_cli.ui.prompts import (
    confirm,
    masked_input,
    prompt_float,
    prompt_int,
    prompt_str,
    select_from_list,
)
from crypto_trading_cli.ui.tables import (
    render_bot_list,
    render_bot_status,
    render_profit,
    render_trades_table,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------

_MENU_OPTIONS = [
    "List Bots",
    "Create & Start Bot",
    "Stop Bot",
    "Restart Bot",
    "Delete Bot",
    "View Bot Status",
    "View Profit",
    "View Open Trades",
    "Force Exit Trade",
]


def run_main_menu(manager: BotManager) -> None:
    """
    Run the interactive main menu loop.

    Displays the numbered menu, reads user input, and dispatches to the
    appropriate sub-flow. Returns to the menu after each sub-flow completes.
    Exits cleanly on KeyboardInterrupt or option 0.
    """
    while True:
        _print_main_menu()
        try:
            raw = input("\nSelect option: ").strip()
        except KeyboardInterrupt:
            rprint("\n[dim]Goodbye![/dim]")
            raise SystemExit(0)

        if raw == "0":
            rprint("[dim]Goodbye![/dim]")
            raise SystemExit(0)

        if not raw.isdigit() or int(raw) < 1 or int(raw) > len(_MENU_OPTIONS):
            rprint("[red]Invalid option. Please try again.[/red]")
            continue

        choice = int(raw)
        try:
            _dispatch(choice, manager)
        except KeyboardInterrupt:
            rprint("\n[dim]Returning to main menu...[/dim]")
        except Exception as exc:
            rprint(f"[red]Unexpected error: {exc}[/red]")
            logger.debug("Unhandled exception in menu flow", exc_info=True)


def _print_main_menu() -> None:
    lines = [
        "  [bold]1.[/bold] List Bots",
        "  [bold]2.[/bold] Create & Start Bot",
        "  [bold]3.[/bold] Stop Bot",
        "  [bold]4.[/bold] Restart Bot",
        "  [bold]5.[/bold] Delete Bot",
        "  [bold]6.[/bold] View Bot Status",
        "  [bold]7.[/bold] View Profit",
        "  [bold]8.[/bold] View Open Trades",
        "  [bold]9.[/bold] Force Exit Trade",
        "  [bold]0.[/bold] Exit",
    ]
    rprint(Panel("\n".join(lines), title="[bold cyan]crypto-cli[/bold cyan]", border_style="cyan"))


def _dispatch(choice: int, manager: BotManager) -> None:
    flows = {
        1: flow_list_bots,
        2: flow_create_bot,
        3: flow_stop_bot,
        4: flow_restart_bot,
        5: flow_delete_bot,
        6: flow_view_status,
        7: flow_view_profit,
        8: flow_view_trades,
        9: flow_force_exit,
    }
    flows[choice](manager)


# ---------------------------------------------------------------------------
# Helper: bot selection
# ---------------------------------------------------------------------------


def _select_bot(manager: BotManager, filter_status: Optional[str] = None) -> Optional[str]:
    """
    Display a numbered list of bots and return the selected bot_id.

    Args:
        filter_status: If set, only show bots with this status.

    Returns:
        The selected bot_id, or None if the user cancelled.
    """
    bots = manager.list_bots()
    if filter_status:
        bots = [b for b in bots if b.status == filter_status]

    if not bots:
        rprint("[dim]No bots found.[/dim]")
        return None

    items = [
        f"{b.id[:8]}  [{b.status}]  {b.strategy.upper()}  {b.exchange}"
        for b in bots
    ]
    idx = select_from_list(items, title="Select a bot")
    if idx is None:
        return None
    return bots[idx].id


# ---------------------------------------------------------------------------
# Flow: List Bots
# ---------------------------------------------------------------------------


def flow_list_bots(manager: BotManager) -> None:
    """Display a table of all bots."""
    bots = manager.list_bots()
    render_bot_list(bots)


# ---------------------------------------------------------------------------
# Flow: Create & Start Bot
# ---------------------------------------------------------------------------


def flow_create_bot(manager: BotManager) -> None:
    """
    6-step wizard:
      1. Select exchange
      2. Set dry-run / sandbox options  ← asked BEFORE credentials
      3. Enter API credentials (optional in dry-run mode)
      4. Select strategy
      5. Configure strategy parameters
      6. Confirm and start
    """
    rprint("\n[bold cyan]Create & Start Bot[/bold cyan]")

    # Step 1: Exchange
    exchange_names = [EXCHANGE_DISPLAY_NAMES[e] for e in SUPPORTED_EXCHANGES]
    idx = select_from_list(exchange_names, title="Step 1: Select exchange")
    if idx is None:
        return
    exchange = SUPPORTED_EXCHANGES[idx]

    # Step 2: Trading mode — ask BEFORE credentials so dry-run users skip API keys
    rprint("\n[bold]Step 2: Trading mode[/bold]")
    rprint("[dim]Dry-run uses paper money — no real orders are placed. "
           "You can skip API keys in dry-run mode.[/dim]")
    dry_run = confirm("Enable dry-run (paper trading, no real orders)?", default=True)
    sandbox = confirm("Enable sandbox/testnet mode?", default=False)

    # Step 3: Credentials (optional when dry-run is enabled)
    rprint("\n[bold]Step 3: API credentials[/bold]")
    if dry_run:
        rprint("[dim]Dry-run mode is ON — API keys are optional. "
               "Press Enter to skip.[/dim]")
    else:
        rprint("[dim]Characters are hidden as you type.[/dim]")

    api_key = _prompt_credential("API Key", required=not dry_run)
    secret = _prompt_credential("Secret", required=not dry_run)

    passphrase: Optional[str] = None
    if exchange in EXCHANGES_REQUIRING_PASSPHRASE:
        if dry_run:
            rprint("[dim]OKX passphrase — press Enter to skip (dry-run mode).[/dim]")
        passphrase_val = _prompt_credential("Passphrase", required=not dry_run)
        passphrase = passphrase_val or None

    # Step 4: Strategy
    strategy_options = ["Grid — buy low / sell high in a price range",
                        "RSI  — buy oversold, sell overbought",
                        "EMA  — EMA crossover trend-following"]
    strategy_keys = ["grid", "rsi", "ema"]
    idx = select_from_list(strategy_options, title="Step 4: Select strategy")
    if idx is None:
        return
    strategy = strategy_keys[idx]

    # Step 5: Strategy parameters
    rprint(f"\n[bold]Step 5: Configure {strategy.upper()} parameters[/bold]")
    params = _collect_strategy_params(strategy)
    if params is None:
        return

    # Step 6: Confirm
    _print_bot_summary(exchange, strategy, params, dry_run, sandbox)
    if not confirm("Start bot?", default=True):
        rprint("[dim]Cancelled.[/dim]")
        return

    rprint("\n[dim]Starting bot...[/dim]")
    try:
        from rich.progress import Progress, SpinnerColumn, TextColumn
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                      transient=True) as progress:
            progress.add_task("Starting Freqtrade...", total=None)
            record = manager.start(CreateBotParams(
                exchange=exchange,
                strategy=strategy,
                params=params,
                api_key=api_key or "",
                secret=secret or "",
                passphrase=passphrase,
                dry_run=dry_run,
                sandbox=sandbox,
            ))
        rprint(f"[green]✓ Bot [bold]{record.id[:8]}[/bold] started on port {record.port}[/green]")
        rprint(f"  Web UI:   [cyan]http://127.0.0.1:{record.port}[/cyan]")
        rprint(f"  Username: freqtrade")
        try:
            from crypto_trading_cli.crypto import decrypt
            pw = decrypt(record.enc_ft_password)
            rprint(f"  Password: [yellow]{pw}[/yellow]")
        except Exception:
            pass
    except (ValueError, RuntimeError) as exc:
        rprint(f"[red]Failed to start bot: {exc}[/red]")


def _prompt_credential(label: str, required: bool = True) -> str:
    """
    Prompt for a credential value with masked input.

    If *required* is False (dry-run mode), the user can press Enter to skip.
    Returns the entered value, or an empty string if skipped.
    """
    prompt_label = f"{label} (press Enter to skip)" if not required else label
    return masked_input(prompt_label, required=required)


def _collect_strategy_params(strategy: str) -> Optional[dict]:
    """Collect and return strategy-specific parameters from the user.

    All parameters have sensible defaults so the user can just press Enter
    to accept them — useful for quick testing.
    """
    rprint("\n[dim]Press Enter to accept the default value shown in brackets.[/dim]")

    # ── Common parameters (all strategies) ───────────────────────────────────
    pair = prompt_str("Trading pair", default="BTC/USDT")
    timeframe = prompt_str("Timeframe (1m/5m/15m/1h)", default="5m")

    rprint("\n[dim]Order type: 'market' fills immediately at current price; "
           "'limit' places an order at a specific price.[/dim]")
    order_type_idx = select_from_list(
        ["market — fill immediately at current price (recommended for testing)",
         "limit  — place order at a specific price"],
        title="Order type",
        allow_cancel=False,
    )
    order_type = "market" if order_type_idx == 0 else "limit"

    invest_amount = prompt_float(
        "Invest amount per trade (USDT, e.g. 100)",
        min_value=0.001,
        default=100.0,
    )
    max_open_trades = prompt_int(
        "Max open trades at once",
        min_value=1,
        default=3,
    )
    stop_loss = prompt_float(
        "Stop loss (e.g. -0.05 for -5%)",
        max_value=-0.001,
        default=-0.05,
    )

    # ── Strategy-specific parameters ─────────────────────────────────────────
    if strategy == "grid":
        rprint("\n[dim]Grid spacing: how far apart each buy/sell level is as a % of price. "
               "Smaller = more trades, larger = fewer trades.[/dim]")
        grid_spacing = prompt_float("Grid spacing %", min_value=0.001, default=0.5)
        return {
            "pair": pair,
            "timeframe": timeframe,
            "order_type": order_type,
            "invest_amount": invest_amount,
            "max_open_trades": max_open_trades,
            "stop_loss": stop_loss,
            "grid_spacing": grid_spacing,
        }

    elif strategy == "rsi":
        rprint("\n[dim]RSI buy: enter long when RSI drops below this (oversold). "
               "RSI sell: exit when RSI rises above this (overbought). "
               "Lower buy threshold = more signals.[/dim]")
        while True:
            rsi_buy = prompt_int("RSI buy threshold (oversold)", min_value=0, max_value=100, default=35)
            rsi_sell = prompt_int("RSI sell threshold (overbought)", min_value=0, max_value=100, default=65)
            if rsi_buy < rsi_sell:
                break
            rprint("[red]RSI buy must be less than RSI sell.[/red]")
        return {
            "pair": pair,
            "timeframe": timeframe,
            "order_type": order_type,
            "invest_amount": invest_amount,
            "max_open_trades": max_open_trades,
            "stop_loss": stop_loss,
            "rsi_buy": rsi_buy,
            "rsi_sell": rsi_sell,
        }

    elif strategy == "ema":
        rprint("\n[dim]EMA short/long: buy when short EMA crosses above long EMA (golden cross). "
               "Smaller periods = more sensitive, more signals.[/dim]")
        while True:
            ema_short = prompt_int("EMA short period", min_value=1, default=9)
            ema_long = prompt_int("EMA long period", min_value=1, default=21)
            if ema_short < ema_long:
                break
            rprint("[red]EMA short must be less than EMA long.[/red]")
        return {
            "pair": pair,
            "timeframe": timeframe,
            "order_type": order_type,
            "invest_amount": invest_amount,
            "max_open_trades": max_open_trades,
            "stop_loss": stop_loss,
            "ema_short": ema_short,
            "ema_long": ema_long,
        }

    return None


def _print_bot_summary(
    exchange: str,
    strategy: str,
    params: dict,
    dry_run: bool,
    sandbox: bool,
) -> None:
    lines = [
        f"[bold]Exchange:[/bold]  {EXCHANGE_DISPLAY_NAMES.get(exchange, exchange)}",
        f"[bold]Strategy:[/bold]  {strategy.upper()}",
        f"[bold]Dry-run:[/bold]   {'Yes' if dry_run else 'No'}",
        f"[bold]Sandbox:[/bold]   {'Yes' if sandbox else 'No'}",
        "",
        "[bold]Parameters:[/bold]",
    ]
    for k, v in params.items():
        lines.append(f"  {k}: {v}")
    rprint(Panel("\n".join(lines), title="[bold]Summary[/bold]", border_style="dim"))


# ---------------------------------------------------------------------------
# Flow: Stop Bot
# ---------------------------------------------------------------------------


def flow_stop_bot(manager: BotManager) -> None:
    """Stop a running bot."""
    bot_id = _select_bot(manager, filter_status="running")
    if not bot_id:
        return
    try:
        record = manager.stop(bot_id)
        rprint(f"[yellow]Bot {record.id[:8]} stopped.[/yellow]")
    except Exception as exc:
        rprint(f"[red]Failed to stop bot: {exc}[/red]")


# ---------------------------------------------------------------------------
# Flow: Restart Bot
# ---------------------------------------------------------------------------


def flow_restart_bot(manager: BotManager) -> None:
    """Restart a stopped or errored bot."""
    bot_id = _select_bot(manager)
    if not bot_id:
        return
    rprint("[dim]Restarting bot...[/dim]")
    try:
        from rich.progress import Progress, SpinnerColumn, TextColumn
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                      transient=True) as progress:
            progress.add_task("Restarting Freqtrade...", total=None)
            record = manager.restart(bot_id)
        rprint(f"[green]✓ Bot {record.id[:8]} restarted on port {record.port}[/green]")
    except Exception as exc:
        rprint(f"[red]Failed to restart bot: {exc}[/red]")


# ---------------------------------------------------------------------------
# Flow: Delete Bot
# ---------------------------------------------------------------------------


def flow_delete_bot(manager: BotManager) -> None:
    """Delete a bot after confirmation."""
    bot_id = _select_bot(manager)
    if not bot_id:
        return
    if not confirm(f"Are you sure you want to delete bot {bot_id[:8]}?", default=False):
        rprint("[dim]Cancelled.[/dim]")
        return
    try:
        manager.delete(bot_id)
        rprint(f"[red]Bot {bot_id[:8]} deleted.[/red]")
    except Exception as exc:
        rprint(f"[red]Failed to delete bot: {exc}[/red]")


# ---------------------------------------------------------------------------
# Flow: View Bot Status
# ---------------------------------------------------------------------------


def flow_view_status(manager: BotManager) -> None:
    """Display detailed status for a selected bot."""
    bot_id = _select_bot(manager)
    if not bot_id:
        return
    try:
        record = manager.get_status(bot_id)
        health = None
        ft_password = None
        if record.status == "running":
            try:
                health = manager.get_health(bot_id)
            except Exception:
                pass
        # Decrypt Web UI password to show in status panel
        try:
            from crypto_trading_cli.crypto import decrypt
            ft_password = decrypt(record.enc_ft_password)
        except Exception:
            pass
        render_bot_status(record, health, ft_password=ft_password)
    except Exception as exc:
        rprint(f"[red]Error: {exc}[/red]")


# ---------------------------------------------------------------------------
# Flow: View Profit
# ---------------------------------------------------------------------------


def flow_view_profit(manager: BotManager) -> None:
    """Display profit summary for a running bot."""
    bot_id = _select_bot(manager, filter_status="running")
    if not bot_id:
        return
    try:
        data = manager.get_profit(bot_id)
        render_profit(data)
    except RuntimeError as exc:
        rprint(f"[red]{exc}[/red]")


# ---------------------------------------------------------------------------
# Flow: View Open Trades
# ---------------------------------------------------------------------------


def flow_view_trades(manager: BotManager) -> None:
    """Display open trades for a running bot."""
    bot_id = _select_bot(manager, filter_status="running")
    if not bot_id:
        return
    try:
        trades = manager.get_open_trades(bot_id)
        render_trades_table(trades)
    except RuntimeError as exc:
        rprint(f"[red]{exc}[/red]")


# ---------------------------------------------------------------------------
# Flow: Force Exit Trade
# ---------------------------------------------------------------------------


def flow_force_exit(manager: BotManager) -> None:
    """Force-exit a specific open trade."""
    bot_id = _select_bot(manager, filter_status="running")
    if not bot_id:
        return

    try:
        trades = manager.get_open_trades(bot_id)
    except RuntimeError as exc:
        rprint(f"[red]{exc}[/red]")
        return

    if not trades:
        rprint("[dim]No open trades.[/dim]")
        return

    render_trades_table(trades)

    trade_id = prompt_str("Enter Trade ID to force-exit")
    if not confirm(f"Force exit trade {trade_id}?", default=False):
        rprint("[dim]Cancelled.[/dim]")
        return

    try:
        result = manager.force_exit(bot_id, trade_id)
        rprint(f"[green]Force exit submitted: {result}[/green]")
    except RuntimeError as exc:
        rprint(f"[red]Force exit failed: {exc}[/red]")
