from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path("data/portfolio.db")

CATEGORY_SEED: list[tuple[str, str, int]] = [
    ("EQUITY", "Equity", 1),
    ("DEBT", "Debt", 2),
    ("GOLD_SILVER", "Gold & Silver", 3),
    ("OTHER_COMMODITIES", "Other Commodities", 4),
    ("CASH", "Cash", 5),
    ("REAL_ESTATE", "Real Estate", 6),
    ("CRYPTO", "Crypto", 7),
    ("ALTERNATIVES", "Alternatives", 8),
    ("INSURANCE", "Insurance", 9),
]

CLASS_SEED: list[tuple[str, str, str, str, int]] = [
    ("STOCKS_EQUITY", "Stocks & Equity", "EQ", "EQUITY", 1),
    ("MUTUAL_FUNDS", "Mutual Funds", "MF", "EQUITY", 2),
    ("INTERNATIONAL", "International", "INTL", "EQUITY", 3),
    ("EMPLOYER_STOCK", "Employer Stock", "ES", "EQUITY", 4),
    ("FD_RD", "FD & RD", "FD", "DEBT", 1),
    ("BONDS", "Bonds", "BND", "DEBT", 2),
    ("DEBT_FUNDS", "Debt Funds", "DF", "DEBT", 3),
    ("EPF_PPF_NPS", "EPF / PPF / NPS", "RET", "DEBT", 4),
    ("SSY", "SSY", "SSY", "DEBT", 5),
    ("LIQUID_FUNDS", "Liquid Funds", "LIQ", "DEBT", 6),
    ("GOLD_SILVER", "Gold & Silver", "Gold", "GOLD_SILVER", 1),
    ("COMMODITIES", "Commodities", "CMD", "OTHER_COMMODITIES", 1),
    ("CASH_SAVINGS", "Cash & Savings", "Cash", "CASH", 1),
    ("ARBITRAGE_FUNDS", "Arbitrage Funds", "ARB", "CASH", 2),
    ("REAL_ESTATE", "Real Estate", "RE", "REAL_ESTATE", 1),
    ("CRYPTO", "Crypto", "CR", "CRYPTO", 1),
    ("OTHER", "Other", "OTH", "ALTERNATIVES", 1),
    ("ULIP", "ULIP", "ULIP", "INSURANCE", 1),
    ("MONEYBACK_INSURANCE", "Moneyback Insurance", "MBI", "INSURANCE", 2),
    ("ENDOWMENT_PLANS", "Endowment Plans", "END", "INSURANCE", 3),
]

EXCHANGE_RATE_SEED: list[tuple[str, float]] = [
    ("INR", 1.0),
    ("USD", 83.0),
    ("EUR", 90.0),
    ("GBP", 106.0),
]


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _create_taxonomy_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS asset_categories (
            category_key TEXT PRIMARY KEY,
            category_name TEXT NOT NULL,
            sort_order INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS asset_classes (
            class_key TEXT PRIMARY KEY,
            class_name TEXT NOT NULL UNIQUE,
            class_code TEXT NOT NULL,
            category_key TEXT NOT NULL,
            sort_order INTEGER NOT NULL,
            FOREIGN KEY (category_key) REFERENCES asset_categories(category_key)
        )
        """
    )


def _seed_taxonomy(connection: sqlite3.Connection) -> None:
    connection.executemany(
        """
        INSERT OR REPLACE INTO asset_categories (category_key, category_name, sort_order)
        VALUES (?, ?, ?)
        """,
        CATEGORY_SEED,
    )
    connection.executemany(
        """
        INSERT OR REPLACE INTO asset_classes (class_key, class_name, class_code, category_key, sort_order)
        VALUES (?, ?, ?, ?, ?)
        """,
        CLASS_SEED,
    )


def _ensure_assets_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            class_key TEXT,
            asset_class TEXT NOT NULL,
            class_code TEXT NOT NULL,
            sub_type TEXT,
            geography TEXT DEFAULT 'India',
            invested REAL NOT NULL,
            value REAL NOT NULL,
            tag TEXT,
            currency TEXT DEFAULT 'INR',
            notes TEXT DEFAULT ''
        )
        """
    )

    columns = _table_columns(connection, "assets")
    if "class_key" not in columns:
        connection.execute("ALTER TABLE assets ADD COLUMN class_key TEXT")
    if "geography" not in columns:
        connection.execute("ALTER TABLE assets ADD COLUMN geography TEXT DEFAULT 'India'")
    if "currency" not in columns:
        connection.execute("ALTER TABLE assets ADD COLUMN currency TEXT DEFAULT 'INR'")
    if "notes" not in columns:
        connection.execute("ALTER TABLE assets ADD COLUMN notes TEXT DEFAULT ''")


def _ensure_exchange_rates_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS exchange_rates (
            currency_code TEXT PRIMARY KEY,
            inr_rate REAL NOT NULL CHECK (inr_rate > 0)
        )
        """
    )


def _ensure_liabilities_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS liabilities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            liability_type TEXT NOT NULL,
            currency TEXT NOT NULL DEFAULT 'INR',
            outstanding_amount REAL NOT NULL,
            interest_rate REAL NOT NULL DEFAULT 0,
            monthly_emi REAL NOT NULL DEFAULT 0,
            start_date TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    columns = _table_columns(connection, "liabilities")
    if "currency" not in columns:
        connection.execute("ALTER TABLE liabilities ADD COLUMN currency TEXT NOT NULL DEFAULT 'INR'")
    if "outstanding_amount" not in columns:
        connection.execute("ALTER TABLE liabilities ADD COLUMN outstanding_amount REAL NOT NULL DEFAULT 0")
    if "interest_rate" not in columns:
        connection.execute("ALTER TABLE liabilities ADD COLUMN interest_rate REAL NOT NULL DEFAULT 0")
    if "monthly_emi" not in columns:
        connection.execute("ALTER TABLE liabilities ADD COLUMN monthly_emi REAL NOT NULL DEFAULT 0")
    if "start_date" not in columns:
        connection.execute("ALTER TABLE liabilities ADD COLUMN start_date TEXT DEFAULT ''")


def _ensure_net_worth_snapshots_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS net_worth_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL DEFAULT '',
            net_worth_inr REAL NOT NULL,
            assets_total_inr REAL NOT NULL,
            liabilities_total_inr REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    columns = _table_columns(connection, "net_worth_snapshots")
    if "label" not in columns:
        connection.execute("ALTER TABLE net_worth_snapshots ADD COLUMN label TEXT NOT NULL DEFAULT ''")


def _ensure_snapshot_line_items_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshot_asset_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            asset_name TEXT NOT NULL,
            asset_class TEXT NOT NULL,
            currency TEXT NOT NULL DEFAULT 'INR',
            original_value REAL NOT NULL,
            value_inr REAL NOT NULL,
            FOREIGN KEY (snapshot_id) REFERENCES net_worth_snapshots(id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshot_liability_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            liability_name TEXT NOT NULL,
            liability_type TEXT NOT NULL,
            currency TEXT NOT NULL DEFAULT 'INR',
            original_outstanding REAL NOT NULL,
            outstanding_inr REAL NOT NULL,
            FOREIGN KEY (snapshot_id) REFERENCES net_worth_snapshots(id)
        )
        """
    )


def _seed_exchange_rates(connection: sqlite3.Connection) -> None:
    connection.executemany(
        """
        INSERT OR IGNORE INTO exchange_rates (currency_code, inr_rate)
        VALUES (?, ?)
        """,
        EXCHANGE_RATE_SEED,
    )


def _migrate_assets(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        UPDATE assets
        SET class_key = (
            SELECT ac.class_key
            FROM asset_classes ac
            WHERE LOWER(ac.class_name) = LOWER(assets.asset_class)
            LIMIT 1
        )
        WHERE class_key IS NULL OR class_key = ''
        """
    )

    connection.execute(
        """
        UPDATE assets
        SET class_key = 'OTHER'
        WHERE class_key IS NULL OR class_key = ''
        """
    )

    connection.execute(
        """
        UPDATE assets
        SET asset_class = (
            SELECT ac.class_name
            FROM asset_classes ac
            WHERE ac.class_key = assets.class_key
        ),
            class_code = (
            SELECT ac.class_code
            FROM asset_classes ac
            WHERE ac.class_key = assets.class_key
        )
        WHERE class_key IS NOT NULL
        """
    )

    connection.execute("UPDATE assets SET currency = 'INR' WHERE currency IS NULL OR currency = ''")
    connection.execute("UPDATE assets SET notes = '' WHERE notes IS NULL")
    connection.execute("UPDATE assets SET geography = 'India' WHERE geography IS NULL OR geography = ''")


def _seed_default_assets(connection: sqlite3.Connection) -> None:
    count = connection.execute("SELECT COUNT(*) AS total FROM assets").fetchone()["total"]
    if count > 0:
        return

    connection.executemany(
        """
        INSERT INTO assets (
            name,
            class_key,
            asset_class,
            class_code,
            sub_type,
            geography,
            invested,
            value,
            tag,
            currency,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "Tata Gold ETF",
                "GOLD_SILVER",
                "Gold & Silver",
                "Gold",
                "-",
                "India",
                10500,
                10256,
                "",
                "INR",
                "",
            ),
            (
                "HDFC Flexi Cap Direct Fund",
                "MUTUAL_FUNDS",
                "Mutual Funds",
                "MF",
                "Flexi Cap",
                "India",
                9000,
                10000,
                "#long-term",
                "INR",
                "",
            ),
        ],
    )


def init_db() -> None:
    with get_connection() as connection:
        _create_taxonomy_tables(connection)
        _seed_taxonomy(connection)
        _ensure_assets_table(connection)
        _ensure_liabilities_table(connection)
        _ensure_net_worth_snapshots_table(connection)
        _ensure_snapshot_line_items_tables(connection)
        _ensure_exchange_rates_table(connection)
        _seed_exchange_rates(connection)
        _migrate_assets(connection)
        _seed_default_assets(connection)


def fetch_assets(category_key: str | None = None, class_key: str | None = None) -> list[sqlite3.Row]:
    query = """
        SELECT
            a.id,
            a.name,
            a.class_key,
            a.asset_class,
            a.class_code,
            a.sub_type,
            a.geography,
            a.invested,
            a.value,
            a.tag,
            a.currency,
            a.notes,
            c.category_key,
            c.category_name
        FROM assets a
        LEFT JOIN asset_classes ac ON ac.class_key = a.class_key
        LEFT JOIN asset_categories c ON c.category_key = ac.category_key
        WHERE (? IS NULL OR c.category_key = ?)
          AND (? IS NULL OR a.class_key = ?)
        ORDER BY a.id ASC
    """
    with get_connection() as connection:
        return connection.execute(query, (category_key, category_key, class_key, class_key)).fetchall()


def fetch_categories() -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT category_key, category_name, sort_order
            FROM asset_categories
            ORDER BY sort_order ASC
            """
        ).fetchall()


def fetch_asset_classes() -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                ac.class_key,
                ac.class_name,
                ac.class_code,
                ac.category_key,
                c.category_name,
                ac.sort_order
            FROM asset_classes ac
            JOIN asset_categories c ON c.category_key = ac.category_key
            ORDER BY c.sort_order ASC, ac.sort_order ASC
            """
        ).fetchall()


def fetch_exchange_rates() -> dict[str, float]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT currency_code, inr_rate
            FROM exchange_rates
            """
        ).fetchall()

    rates = {row["currency_code"].upper(): float(row["inr_rate"]) for row in rows}
    rates["INR"] = 1.0
    return rates


def fetch_liabilities() -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                id,
                name,
                liability_type,
                currency,
                outstanding_amount,
                interest_rate,
                monthly_emi,
                start_date,
                created_at
            FROM liabilities
            ORDER BY outstanding_amount DESC, id DESC
            """
        ).fetchall()


def fetch_net_worth_snapshots(limit: int | None = None) -> list[sqlite3.Row]:
    query = """
        SELECT
            id,
            label,
            net_worth_inr,
            assets_total_inr,
            liabilities_total_inr,
            created_at
        FROM net_worth_snapshots
        ORDER BY datetime(created_at) DESC, id DESC
    """
    params: tuple[object, ...] = ()
    if limit is not None and limit > 0:
        query += " LIMIT ?"
        params = (int(limit),)

    with get_connection() as connection:
        return connection.execute(query, params).fetchall()


def fetch_snapshot_asset_items(snapshot_id: int) -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                id,
                snapshot_id,
                asset_name,
                asset_class,
                currency,
                original_value,
                value_inr
            FROM snapshot_asset_items
            WHERE snapshot_id = ?
            ORDER BY value_inr DESC, id ASC
            """,
            (snapshot_id,),
        ).fetchall()


def fetch_snapshot_liability_items(snapshot_id: int) -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                id,
                snapshot_id,
                liability_name,
                liability_type,
                currency,
                original_outstanding,
                outstanding_inr
            FROM snapshot_liability_items
            WHERE snapshot_id = ?
            ORDER BY outstanding_inr DESC, id ASC
            """,
            (snapshot_id,),
        ).fetchall()


def fetch_category_filters() -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                c.category_key,
                c.category_name,
                COUNT(a.id) AS asset_count,
                c.sort_order
            FROM asset_categories c
            LEFT JOIN asset_classes ac ON ac.category_key = c.category_key
            LEFT JOIN assets a ON a.class_key = ac.class_key
            GROUP BY c.category_key, c.category_name, c.sort_order
            HAVING COUNT(a.id) > 0
            ORDER BY c.sort_order ASC
            """
        ).fetchall()


def fetch_class_filters(category_key: str | None = None) -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                ac.class_key,
                ac.class_name,
                ac.category_key,
                COUNT(a.id) AS asset_count,
                ac.sort_order
            FROM asset_classes ac
            LEFT JOIN assets a ON a.class_key = ac.class_key
            WHERE (? IS NULL OR ac.category_key = ?)
            GROUP BY ac.class_key, ac.class_name, ac.category_key, ac.sort_order
            HAVING COUNT(a.id) > 0
            ORDER BY ac.sort_order ASC
            """,
            (category_key, category_key),
        ).fetchall()


def add_asset(
    name: str,
    class_key: str,
    sub_type: str,
    geography: str,
    invested: float,
    value: float,
    tag: str,
    currency: str,
    notes: str,
) -> None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT class_name, class_code
            FROM asset_classes
            WHERE class_key = ?
            """,
            (class_key,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown class_key: {class_key}")

        connection.execute(
            """
            INSERT INTO assets (
                name,
                class_key,
                asset_class,
                class_code,
                sub_type,
                geography,
                invested,
                value,
                tag,
                currency,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                class_key,
                row["class_name"],
                row["class_code"],
                sub_type,
                geography,
                invested,
                value,
                tag,
                currency,
                notes,
            ),
        )


def add_liability(
    name: str,
    liability_type: str,
    currency: str,
    outstanding_amount: float,
    interest_rate: float,
    monthly_emi: float,
    start_date: str,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO liabilities (
                name,
                liability_type,
                currency,
                outstanding_amount,
                interest_rate,
                monthly_emi,
                start_date
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                liability_type,
                currency,
                outstanding_amount,
                interest_rate,
                monthly_emi,
                start_date,
            ),
        )


def add_net_worth_snapshot(
    label: str,
    net_worth_inr: float,
    assets_total_inr: float,
    liabilities_total_inr: float,
    snapshot_asset_items: list[tuple[str, str, str, float, float]] | None = None,
    snapshot_liability_items: list[tuple[str, str, str, float, float]] | None = None,
) -> int:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO net_worth_snapshots (
                label,
                net_worth_inr,
                assets_total_inr,
                liabilities_total_inr
            )
            VALUES (?, ?, ?, ?)
            """,
            (label, net_worth_inr, assets_total_inr, liabilities_total_inr),
        )
        snapshot_id = int(cursor.lastrowid)

        if snapshot_asset_items:
            connection.executemany(
                """
                INSERT INTO snapshot_asset_items (
                    snapshot_id,
                    asset_name,
                    asset_class,
                    currency,
                    original_value,
                    value_inr
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (snapshot_id, asset_name, asset_class, currency, original_value, value_inr)
                    for asset_name, asset_class, currency, original_value, value_inr in snapshot_asset_items
                ],
            )

        if snapshot_liability_items:
            connection.executemany(
                """
                INSERT INTO snapshot_liability_items (
                    snapshot_id,
                    liability_name,
                    liability_type,
                    currency,
                    original_outstanding,
                    outstanding_inr
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot_id,
                        liability_name,
                        liability_type,
                        currency,
                        original_outstanding,
                        outstanding_inr,
                    )
                    for liability_name, liability_type, currency, original_outstanding, outstanding_inr in snapshot_liability_items
                ],
            )

        return snapshot_id


def update_liability(
    liability_id: int,
    name: str,
    liability_type: str,
    currency: str,
    outstanding_amount: float,
    interest_rate: float,
    monthly_emi: float,
    start_date: str,
) -> int:
    with get_connection() as connection:
        result = connection.execute(
            """
            UPDATE liabilities
            SET name = ?,
                liability_type = ?,
                currency = ?,
                outstanding_amount = ?,
                interest_rate = ?,
                monthly_emi = ?,
                start_date = ?
            WHERE id = ?
            """,
            (
                name,
                liability_type,
                currency,
                outstanding_amount,
                interest_rate,
                monthly_emi,
                start_date,
                liability_id,
            ),
        )
        return result.rowcount


def delete_liability(liability_id: int) -> int:
    with get_connection() as connection:
        result = connection.execute(
            """
            DELETE FROM liabilities
            WHERE id = ?
            """,
            (liability_id,),
        )
        return result.rowcount


def update_assets_class(asset_ids: list[int], class_key: str) -> int:
    if not asset_ids:
        return 0

    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT class_name, class_code
            FROM asset_classes
            WHERE class_key = ?
            """,
            (class_key,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown class_key: {class_key}")

        placeholders = ",".join("?" for _ in asset_ids)
        params: list[object] = [class_key, row["class_name"], row["class_code"], *asset_ids]
        result = connection.execute(
            f"""
            UPDATE assets
            SET class_key = ?, asset_class = ?, class_code = ?
            WHERE id IN ({placeholders})
            """,
            params,
        )
        return result.rowcount


def delete_assets(asset_ids: list[int]) -> int:
    if not asset_ids:
        return 0

    with get_connection() as connection:
        placeholders = ",".join("?" for _ in asset_ids)
        result = connection.execute(
            f"DELETE FROM assets WHERE id IN ({placeholders})",
            asset_ids,
        )
        return result.rowcount


def update_asset_tag(asset_id: int, tag: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE assets
            SET tag = ?
            WHERE id = ?
            """,
            (tag, asset_id),
        )


def update_asset_details(
    asset_id: int,
    class_key: str,
    name: str,
    sub_type: str,
    geography: str,
    invested: float,
    value: float,
    tag: str,
    currency: str,
    notes: str,
) -> None:
    with get_connection() as connection:
        class_row = connection.execute(
            """
            SELECT class_name, class_code
            FROM asset_classes
            WHERE class_key = ?
            """,
            (class_key,),
        ).fetchone()
        if class_row is None:
            raise ValueError(f"Unknown class_key: {class_key}")

        connection.execute(
            """
            UPDATE assets
            SET class_key = ?,
                asset_class = ?,
                class_code = ?,
                name = ?,
                sub_type = ?,
                geography = ?,
                invested = ?,
                value = ?,
                tag = ?,
                currency = ?,
                notes = ?
            WHERE id = ?
            """,
            (
                class_key,
                class_row["class_name"],
                class_row["class_code"],
                name,
                sub_type,
                geography,
                invested,
                value,
                tag,
                currency,
                notes,
                asset_id,
            ),
        )
