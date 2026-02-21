"""
Output Formatter.
Converts product data to Pandas DataFrame, CSV, and optionally stores in PostgreSQL.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger("scraper_agent")


class OutputFormatter:
    """Formats and exports product data."""

    COLUMN_ORDER = [
        "name", "price", "price_numeric", "availability",
        "product_url", "image_url",
    ]

    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def to_dataframe(self, products: List[Dict[str, Any]]) -> pd.DataFrame:
        """
        Convert product data to a Pandas DataFrame.

        Args:
            products: List of product dictionaries

        Returns:
            Structured DataFrame with product data
        """
        if not products:
            logger.warning("No products to convert to DataFrame")
            return pd.DataFrame(columns=self.COLUMN_ORDER)

        df = pd.DataFrame(products)

        # Reorder columns (keep any extra columns at the end)
        ordered_cols = [c for c in self.COLUMN_ORDER if c in df.columns]
        extra_cols = [c for c in df.columns if c not in self.COLUMN_ORDER]
        df = df[ordered_cols + extra_cols]

        # Sort by name
        if "name" in df.columns:
            df = df.sort_values("name", na_position="last").reset_index(drop=True)

        logger.info(f"Created DataFrame with {len(df)} products and {len(df.columns)} columns")
        return df

    def to_csv(
        self,
        df: pd.DataFrame,
        filename: str = "products.csv",
        encoding: str = "utf-8-sig",
    ) -> str:
        """
        Export DataFrame to CSV file.

        Args:
            df: Product DataFrame
            filename: Output filename
            encoding: File encoding (utf-8-sig for Excel compatibility)

        Returns:
            Path to the exported CSV file
        """
        filepath = self.output_dir / filename
        df.to_csv(filepath, index=False, encoding=encoding)
        logger.info(f"Exported {len(df)} products to {filepath}")
        return str(filepath)

    def to_json(
        self,
        df: pd.DataFrame,
        filename: str = "products.json",
    ) -> str:
        """
        Export DataFrame to JSON file.

        Args:
            df: Product DataFrame
            filename: Output filename

        Returns:
            Path to the exported JSON file
        """
        filepath = self.output_dir / filename
        df.to_json(filepath, orient="records", indent=2, force_ascii=False)
        logger.info(f"Exported {len(df)} products to {filepath}")
        return str(filepath)

    def to_excel(
        self,
        df: pd.DataFrame,
        filename: str = "products.xlsx",
    ) -> str:
        """
        Export DataFrame to Excel file.

        Args:
            df: Product DataFrame
            filename: Output filename

        Returns:
            Path to the exported Excel file
        """
        filepath = self.output_dir / filename
        df.to_excel(filepath, index=False, engine="openpyxl")
        logger.info(f"Exported {len(df)} products to {filepath}")
        return str(filepath)

    def to_database(
        self,
        df: pd.DataFrame,
        connection_string: str,
        table_name: str = "products",
        if_exists: str = "append",
    ) -> int:
        """
        Store product data in a PostgreSQL database.

        Args:
            df: Product DataFrame
            connection_string: SQLAlchemy connection string
            table_name: Target table name
            if_exists: Behavior when table exists ('append', 'replace', 'fail')

        Returns:
            Number of rows inserted
        """
        try:
            from sqlalchemy import create_engine

            engine = create_engine(connection_string)

            # Add metadata columns
            from datetime import datetime
            df_copy = df.copy()
            df_copy["scraped_at"] = datetime.utcnow()

            rows = df_copy.to_sql(
                table_name,
                engine,
                if_exists=if_exists,
                index=False,
                method="multi",
            )

            logger.info(
                f"Stored {len(df_copy)} products in database "
                f"table '{table_name}'"
            )
            return len(df_copy)

        except ImportError:
            logger.error(
                "SQLAlchemy not installed. Run: pip install sqlalchemy psycopg2-binary"
            )
            return 0
        except Exception as e:
            logger.error(f"Database error: {e}")
            return 0

    def print_summary(self, df: pd.DataFrame) -> None:
        """Print a formatted summary of the scraped data."""
        if df.empty:
            print("\n[!] No products were scraped.")
            return

        print("\n" + "=" * 70)
        print(f"  SCRAPING RESULTS SUMMARY")
        print("=" * 70)
        print(f"  Total Products:  {len(df)}")

        if "price_numeric" in df.columns:
            prices = df["price_numeric"].dropna()
            if not prices.empty:
                print(f"  Price Range:     ${prices.min():.2f} - ${prices.max():.2f}")
                print(f"  Average Price:   ${prices.mean():.2f}")

        if "availability" in df.columns:
            avail = df["availability"].value_counts()
            print(f"  Availability:")
            for status, count in avail.items():
                print(f"    {status}: {count}")

        if "image_url" in df.columns:
            img_count = df["image_url"].notna().sum()
            print(f"  With Images:     {img_count}/{len(df)}")

        if "product_url" in df.columns:
            url_count = df["product_url"].notna().sum()
            print(f"  With URLs:       {url_count}/{len(df)}")

        print("=" * 70)

        # Show first few products
        print(f"\n  First 5 Products:")
        print("-" * 70)
        display_cols = ["name", "price", "availability"]
        display_cols = [c for c in display_cols if c in df.columns]
        print(df[display_cols].head(5).to_string(index=False))
        print()
