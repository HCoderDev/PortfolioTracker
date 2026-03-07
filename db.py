from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path("data/portfolio.db")

CATEGORY_SEED: list[tuple[str, str, int, float]] = [
    ("EQUITY", "Equity", 1, 50.0),
    ("DEBT", "Debt", 2, 15.0),
    ("GOLD_SILVER", "Gold & Silver", 3, 15.0),
    ("OTHER_COMMODITIES", "Other Commodities", 4, 0.0),
    ("CASH", "Cash", 5, 15.0),
    ("REAL_ESTATE", "Real Estate", 6, 0.0),
    ("CRYPTO", "Crypto", 7, 0.0),
    ("ALTERNATIVES", "Alternatives", 8, 0.0),
    ("INSURANCE", "Insurance", 9, 5.0),
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
            sort_order INTEGER NOT NULL,
            target_percentage REAL DEFAULT 0.0
        )
        """
    )
    
    columns = _table_columns(connection, "asset_categories")
    if "target_percentage" not in columns:
        connection.execute("ALTER TABLE asset_categories ADD COLUMN target_percentage REAL DEFAULT 0.0")
        
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
        INSERT INTO asset_categories (category_key, category_name, sort_order, target_percentage)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(category_key) DO UPDATE SET 
            category_name=excluded.category_name, 
            sort_order=excluded.sort_order,
            target_percentage=COALESCE(NULLIF(asset_categories.target_percentage, 0), excluded.target_percentage)
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


def _ensure_user_settings_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS user_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            age INTEGER DEFAULT NULL,
            monthly_income REAL DEFAULT NULL,
            monthly_expense REAL DEFAULT NULL,
            monthly_savings REAL DEFAULT NULL,
            display_name TEXT DEFAULT NULL,
            email TEXT DEFAULT NULL,
            password_hash TEXT DEFAULT NULL,
            app_pin TEXT DEFAULT NULL,
            base_currency TEXT DEFAULT 'INR',
            auth_registered INTEGER NOT NULL DEFAULT 0,
            keep_logged_in INTEGER NOT NULL DEFAULT 0,
            logged_in INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    columns = _table_columns(connection, "user_settings")
    if "auth_registered" not in columns:
        connection.execute("ALTER TABLE user_settings ADD COLUMN auth_registered INTEGER NOT NULL DEFAULT 0")
    if "keep_logged_in" not in columns:
        connection.execute("ALTER TABLE user_settings ADD COLUMN keep_logged_in INTEGER NOT NULL DEFAULT 0")
    if "logged_in" not in columns:
        connection.execute("ALTER TABLE user_settings ADD COLUMN logged_in INTEGER NOT NULL DEFAULT 0")
    # Ensure the single row exists immediately so frontend can blindly query/update it
    connection.execute(
        """
        INSERT OR IGNORE INTO user_settings (id, base_currency) VALUES (1, 'INR')
        """
    )
    connection.execute("UPDATE user_settings SET auth_registered = 0 WHERE auth_registered IS NULL")
    connection.execute("UPDATE user_settings SET keep_logged_in = 0 WHERE keep_logged_in IS NULL")
    connection.execute("UPDATE user_settings SET logged_in = 0 WHERE logged_in IS NULL")


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
        _ensure_user_settings_table(connection)
        _ensure_exchange_rates_table(connection)
        _ensure_goals_tables(connection)
        _seed_exchange_rates(connection)
        _migrate_assets(connection)


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
            SELECT category_key, category_name, sort_order, target_percentage
            FROM asset_categories
            ORDER BY sort_order ASC
            """
        ).fetchall()

def update_category_targets(targets: dict[str, float]) -> None:
    with get_connection() as connection:
        connection.executemany(
            """
            UPDATE asset_categories
            SET target_percentage = ?
            WHERE category_key = ?
            """,
            [(pct, key) for key, pct in targets.items()]
        )


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


def delete_snapshot(snapshot_id: int) -> int:
    with get_connection() as connection:
        connection.execute("DELETE FROM snapshot_asset_items WHERE snapshot_id = ?", (snapshot_id,))
        connection.execute("DELETE FROM snapshot_liability_items WHERE snapshot_id = ?", (snapshot_id,))
        result = connection.execute("DELETE FROM net_worth_snapshots WHERE id = ?", (snapshot_id,))
        return result.rowcount


def fetch_user_settings() -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute("SELECT * FROM user_settings WHERE id = 1").fetchone()


def register_auth_user(
    display_name: str,
    email: str,
    password_hash: str,
    app_pin: str | None,
    keep_logged_in: bool,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE user_settings
            SET
                display_name = ?,
                email = ?,
                password_hash = ?,
                app_pin = ?,
                auth_registered = 1,
                keep_logged_in = ?,
                logged_in = 1
            WHERE id = 1
            """,
            (
                display_name,
                email,
                password_hash,
                app_pin,
                1 if keep_logged_in else 0,
            ),
        )
        connection.commit()


def update_auth_session(logged_in: bool, keep_logged_in: bool | None = None) -> None:
    with get_connection() as connection:
        if keep_logged_in is None:
            connection.execute(
                "UPDATE user_settings SET logged_in = ? WHERE id = 1",
                (1 if logged_in else 0,),
            )
        else:
            connection.execute(
                "UPDATE user_settings SET logged_in = ?, keep_logged_in = ? WHERE id = 1",
                (1 if logged_in else 0, 1 if keep_logged_in else 0),
            )
        connection.commit()


def clear_auth_session() -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE user_settings SET logged_in = 0, keep_logged_in = 0 WHERE id = 1"
        )
        connection.commit()


def reset_auth_password(email: str, app_pin: str, new_password_hash: str) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT email, app_pin, auth_registered FROM user_settings WHERE id = 1"
        ).fetchone()
        if row is None or int(row["auth_registered"] or 0) != 1:
            return False
        if (row["email"] or "").strip().casefold() != email.strip().casefold():
            return False
        if (row["app_pin"] or "").strip() != app_pin.strip():
            return False

        connection.execute(
            """
            UPDATE user_settings
            SET password_hash = ?, logged_in = 0, keep_logged_in = 0
            WHERE id = 1
            """,
            (new_password_hash,),
        )
        connection.commit()
        return True


def update_financial_profile(
    age: int | None, income: float | None, expense: float | None, savings: float | None
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE user_settings 
            SET age = ?, monthly_income = ?, monthly_expense = ?, monthly_savings = ?
            WHERE id = 1
            """,
            (age, income, expense, savings),
        )
        connection.commit()


def update_user_profile(display_name: str | None, email: str | None) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE user_settings 
            SET display_name = ?, email = ?
            WHERE id = 1
            """,
            (display_name, email),
        )
        connection.commit()


def update_security(password_hash: str | None, app_pin: str | None) -> None:
    with get_connection() as connection:
        if password_hash is not None and app_pin is not None:
             connection.execute("UPDATE user_settings SET password_hash = ?, app_pin = ? WHERE id = 1", (password_hash, app_pin))
        elif password_hash is not None:
             connection.execute("UPDATE user_settings SET password_hash = ? WHERE id = 1", (password_hash,))
        elif app_pin is not None:
             connection.execute("UPDATE user_settings SET app_pin = ? WHERE id = 1", (app_pin,))
        connection.commit()


def update_base_currency(currency: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE user_settings SET base_currency = ? WHERE id = 1",
            (currency,),
        )
        connection.commit()


def _ensure_goals_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            target_amount REAL NOT NULL,
            currency TEXT DEFAULT 'INR',
            target_date TEXT NOT NULL,
            expected_return_pct REAL DEFAULT 7.0,
            asset_class_key TEXT,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            paused_at TEXT,
            achieved_at TEXT
        )
        """
    )
    columns = _table_columns(connection, "goals")
    if "status" not in columns:
        connection.execute("ALTER TABLE goals ADD COLUMN status TEXT NOT NULL DEFAULT 'ACTIVE'")
    if "created_at" not in columns:
        connection.execute("ALTER TABLE goals ADD COLUMN created_at TEXT")
    if "paused_at" not in columns:
        connection.execute("ALTER TABLE goals ADD COLUMN paused_at TEXT")
    if "achieved_at" not in columns:
        connection.execute("ALTER TABLE goals ADD COLUMN achieved_at TEXT")
    connection.execute("UPDATE goals SET status = UPPER(COALESCE(status, 'ACTIVE'))")
    connection.execute("UPDATE goals SET status = 'ACTIVE' WHERE status NOT IN ('ACTIVE', 'PAUSED', 'ACHIEVED')")
    connection.execute("UPDATE goals SET created_at = CURRENT_TIMESTAMP WHERE COALESCE(created_at, '') = ''")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS goal_linked_assets (
            goal_id INTEGER NOT NULL,
            asset_id INTEGER NOT NULL,
            FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE,
            FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE,
            PRIMARY KEY (goal_id, asset_id)
        )
        """
    )


def create_goal(
    name: str,
    target_amount: float,
    target_date: str,
    expected_return_pct: float,
    asset_class_key: str | None,
    linked_asset_ids: list[int] | None = None,
) -> int:
    asset_ids = linked_asset_ids or []
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO goals (
                name, target_amount, currency, target_date, expected_return_pct, asset_class_key, status, created_at
            )
            VALUES (?, ?, 'INR', ?, ?, ?, 'ACTIVE', CURRENT_TIMESTAMP)
            """,
            (name, target_amount, target_date, expected_return_pct, asset_class_key)
        )
        goal_id = cursor.lastrowid
        
        if asset_ids:
            for aid in asset_ids:
                cursor.execute("INSERT INTO goal_linked_assets (goal_id, asset_id) VALUES (?, ?)", (goal_id, aid))
        
        connection.commit()
        return goal_id


def fetch_goals() -> list[dict]:
    with get_connection() as connection:
        goals = connection.execute(
            """
            SELECT
                id,
                name,
                target_amount,
                currency,
                target_date,
                expected_return_pct,
                asset_class_key,
                COALESCE(status, 'ACTIVE') AS status,
                COALESCE(created_at, '') AS created_at,
                paused_at,
                achieved_at
            FROM goals
            ORDER BY id DESC
            """
        ).fetchall()
        result = []
        for g in goals:
            goal_dict = dict(g)
            links = connection.execute("SELECT asset_id FROM goal_linked_assets WHERE goal_id = ?", (g["id"],)).fetchall()
            goal_dict["linked_asset_ids"] = [l["asset_id"] for l in links]
            result.append(goal_dict)
        return result


def fetch_goal_by_id(goal_id: int) -> dict | None:
    with get_connection() as connection:
        goal_row = connection.execute(
            """
            SELECT
                id,
                name,
                target_amount,
                currency,
                target_date,
                expected_return_pct,
                asset_class_key,
                COALESCE(status, 'ACTIVE') AS status,
                COALESCE(created_at, '') AS created_at,
                paused_at,
                achieved_at
            FROM goals
            WHERE id = ?
            """,
            (goal_id,),
        ).fetchone()
        if goal_row is None:
            return None
        goal_dict = dict(goal_row)
        links = connection.execute(
            "SELECT asset_id FROM goal_linked_assets WHERE goal_id = ?",
            (goal_id,),
        ).fetchall()
        goal_dict["linked_asset_ids"] = [l["asset_id"] for l in links]
        return goal_dict


def update_goal(
    goal_id: int,
    name: str,
    target_amount: float,
    target_date: str,
    expected_return_pct: float,
    asset_class_key: str | None,
    linked_asset_ids: list[int] | None = None,
) -> None:
    asset_ids = linked_asset_ids or []
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE goals
            SET
                name = ?,
                target_amount = ?,
                target_date = ?,
                expected_return_pct = ?,
                asset_class_key = ?
            WHERE id = ?
            """,
            (name, target_amount, target_date, expected_return_pct, asset_class_key, goal_id),
        )
        connection.execute("DELETE FROM goal_linked_assets WHERE goal_id = ?", (goal_id,))
        for aid in asset_ids:
            connection.execute("INSERT INTO goal_linked_assets (goal_id, asset_id) VALUES (?, ?)", (goal_id, aid))
        connection.commit()


def update_goal_status(goal_id: int, status: str) -> None:
    normalized = (status or "ACTIVE").strip().upper()
    if normalized not in {"ACTIVE", "PAUSED", "ACHIEVED"}:
        raise ValueError(f"Unsupported goal status: {status}")

    with get_connection() as connection:
        if normalized == "PAUSED":
            connection.execute(
                """
                UPDATE goals
                SET status = 'PAUSED',
                    paused_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (goal_id,),
            )
        elif normalized == "ACHIEVED":
            connection.execute(
                """
                UPDATE goals
                SET status = 'ACHIEVED',
                    achieved_at = CURRENT_TIMESTAMP,
                    paused_at = NULL
                WHERE id = ?
                """,
                (goal_id,),
            )
        else:
            connection.execute(
                """
                UPDATE goals
                SET status = 'ACTIVE',
                    paused_at = NULL,
                    achieved_at = NULL
                WHERE id = ?
                """,
                (goal_id,),
            )
        connection.commit()


def delete_goal(goal_id: int) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM goal_linked_assets WHERE goal_id = ?", (goal_id,))
        connection.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
        connection.commit()


def link_goal_assets(goal_id: int, asset_ids: list[int]) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM goal_linked_assets WHERE goal_id = ?", (goal_id,))
        for aid in asset_ids:
            connection.execute("INSERT INTO goal_linked_assets (goal_id, asset_id) VALUES (?, ?)", (goal_id, aid))
        connection.commit()
