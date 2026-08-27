import pandas as pd
import numpy as np
from typing import Dict, Any, List, Union


class DataPreprocessor:
    """
    Tiền xử lý dữ liệu thu thập từ GitHub trước khi đưa vào các Core Models.
    """

    @staticmethod
    def clean_repository_data(raw_data: Union[Dict[str, Any], pd.DataFrame]) -> pd.DataFrame:
        """
        Làm sạch dữ liệu repository (xử lý null, chuẩn hóa kiểu dữ liệu).
        """
        if isinstance(raw_data, dict):
            df = pd.DataFrame([raw_data])
        elif isinstance(raw_data, list):
            df = pd.DataFrame(raw_data)
        else:
            df = raw_data.copy()

        numeric_cols = [
            'stars', 'forks', 'open_issues', 'commits_count',
            'contributors_count', 'recent_commits_30d', 'closed_issues_30d'
        ]
        
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(float)
            else:
                df[col] = 0.0

        if 'pushed_at' in df.columns:
            df['pushed_at'] = pd.to_datetime(df['pushed_at'], errors='coerce')
        if 'created_at' in df.columns:
            df['created_at'] = pd.to_datetime(df['created_at'], errors='coerce')

        return df

    @staticmethod
    def scale_min_max(series: pd.Series, min_val: float = 0.0, max_val: float = 100.0) -> pd.Series:
        """
        Min-Max Scaling cho một feature về khoảng [min_val, max_val].
        """
        s_min = series.min()
        s_max = series.max()
        if s_max == s_min:
            return pd.Series(max_val / 2.0, index=series.index)
        return (series - s_min) / (s_max - s_min) * (max_val - min_val) + min_val
