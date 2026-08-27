import pandas as pd
from typing import List, Dict, Any


class DataAggregator:
    """
    Gom nhóm dữ liệu chuỗi thời gian (Time-Series Aggregation) cho Trend Analysis và Forecasting.
    """

    @staticmethod
    def aggregate_technology_timeseries(
        records: List[Dict[str, Any]], 
        time_col: str = "timestamp", 
        tech_col: str = "technology",
        freq: str = "MS"  # Month Start
    ) -> pd.DataFrame:
        """
        Aggregate dữ liệu theo chuỗi thời gian (hàng tháng).
        """
        if not records:
            return pd.DataFrame(columns=[time_col, tech_col, 'repository_count', 'stars', 'forks', 'commits', 'contributors'])

        df = pd.DataFrame(records)
        df[time_col] = pd.to_datetime(df[time_col])

        agg_dict = {
            'repository_count': 'sum' if 'repository_count' in df.columns else 'count',
            'stars': 'sum' if 'stars' in df.columns else 'count',
            'forks': 'sum' if 'forks' in df.columns else 'count',
            'commits': 'sum' if 'commits' in df.columns else 'count',
            'contributors': 'sum' if 'contributors' in df.columns else 'count'
        }

        # Select available columns
        agg_dict = {k: v for k, v in agg_dict.items() if k in df.columns or v == 'count'}

        resampled = (
            df.groupby([tech_col, pd.Grouper(key=time_col, freq=freq)])
            .agg(agg_dict)
            .reset_index()
        )

        return resampled
