import os
import pandas as pd
import secure_data

DATA_DIR = "./data"

class DataAdapter:
    """Unified database connector. Supports environment toggles for local Parquet files vs SQL server tables."""
    def __init__(self):
        # Modes: 'demo' (parquet) or 'production' (live database connection)
        self.source_mode = os.getenv("HOTWORX_DATA_SOURCE", "demo").lower()
        self.conn_str = os.getenv("HOTWORX_DB_CONN")

    def load_table(self, table_name: str) -> pd.DataFrame:
        """Load a table in-memory. Automatically handles decryption for sensitive tables."""
        if self.source_mode == "production":
            if not self.conn_str:
                raise ValueError("DataAdapter CONFIG ERROR: HOTWORX_DB_CONN environment variable is unset in production mode.")
            print(f"[Data Adapter PRODUCTION] Pulling table '{table_name}' from target database server...")
            try:
                import sqlalchemy as sa
                engine = sa.create_engine(self.conn_str)
                with engine.connect() as conn:
                    return pd.read_sql(f"SELECT * FROM {table_name}", conn)
            except Exception as e:
                # Fail loudly in production if data pull fails
                raise RuntimeError(f"DataAdapter PRODUCTION FAILURE during extraction of '{table_name}': {str(e)}")
        else:
            # Sandbox / Demo Mode
            file_name = f"{table_name}.parquet"
            file_path = os.path.join(DATA_DIR, file_name)
            
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"DataAdapter Sandbox Error: Parquet table not found at {file_path}")
                
            # Handle decrypted identity mapping automatically
            if table_name == "int_member_identity":
                return secure_data.read_encrypted_parquet(file_path)
                
            return pd.read_parquet(file_path)

def load_dataset(table_name: str) -> pd.DataFrame:
    adapter = DataAdapter()
    return adapter.load_table(table_name)
