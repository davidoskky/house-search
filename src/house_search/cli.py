from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright
from rich.console import Console
from rich.table import Table

from .scrapers.fotocasa import FotocasaScraper
from .scrapers.idealista import IdealistaScraper
from .storage import get_db, load_listings, save_listings

console = Console()


async def run_scrapers(
    sources: list[str],
    max_pages: int,
    headless: bool,
) -> None:
    scrapers = []
    if "idealista" in sources:
        scrapers.append(IdealistaScraper(max_pages=max_pages, headless=headless))
    if "fotocasa" in sources:
        scrapers.append(FotocasaScraper(max_pages=max_pages, headless=headless))

    all_listings = []

    async with async_playwright() as pw:
        browser = await pw.firefox.launch(headless=headless)
        try:
            for scraper in scrapers:
                console.rule(f"[bold]{scraper.source}")
                async for listing in scraper.scrape_with_browser(browser):
                    all_listings.append(listing)
                    console.print(
                        f"  [green]+[/green] {listing.title[:55]:<55} "
                        f"[bold cyan]{listing.price:.0f}€[/bold cyan]"
                        + (f"  {listing.rooms}h" if listing.rooms else "")
                        + (f"  {listing.size_m2:.0f}m²" if listing.size_m2 else "")
                    )
        finally:
            await browser.close()

    if all_listings:
        db = get_db()
        save_listings(all_listings, db)
        console.print(f"\n[bold green]Saved {len(all_listings)} listings to database.[/bold green]")
    else:
        console.print("[yellow]No listings found.[/yellow]")


def show_listings() -> None:
    listings = load_listings()
    if not listings:
        console.print("[yellow]No listings in database. Run 'scrape' first.[/yellow]")
        return

    table = Table(title=f"Listings ({len(listings)} total)", show_lines=False)
    table.add_column("Source", style="dim", width=10)
    table.add_column("Title", width=45)
    table.add_column("Price", justify="right", style="cyan")
    table.add_column("Rooms", justify="center")
    table.add_column("Size", justify="right")
    table.add_column("€/room", justify="right", style="green")

    for lst in sorted(listings, key=lambda x: x.price):
        table.add_row(
            lst.source,
            lst.title[:44],
            f"{lst.price:.0f}€",
            str(lst.rooms) if lst.rooms else "-",
            f"{lst.size_m2:.0f}m²" if lst.size_m2 else "-",
            f"{lst.price_per_room:.0f}€" if lst.price_per_room else "-",
        )
    console.print(table)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="House search scraper for Santiago de Compostela")
    subparsers = parser.add_subparsers(dest="command")

    scrape_p = subparsers.add_parser("scrape", help="Run scrapers")
    scrape_p.add_argument(
        "--sources",
        nargs="+",
        default=["idealista", "fotocasa"],
        choices=["idealista", "fotocasa"],
    )
    scrape_p.add_argument("--max-pages", type=int, default=5)
    scrape_p.add_argument("--no-headless", action="store_true", help="Show browser window")

    subparsers.add_parser("list", help="Show stored listings")

    args = parser.parse_args()

    if args.command == "scrape":
        asyncio.run(run_scrapers(args.sources, args.max_pages, headless=not args.no_headless))
    elif args.command == "list":
        show_listings()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
