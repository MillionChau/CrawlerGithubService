import pandas as pd
import numpy as np
from typing import Dict, Any


class TrendFeatureExtractor:
    """
    Trích xuất chỉ số xu hướng (Growth Rate, Momentum) cho xu hướng công nghệ.
    """

    @staticmethod
    def calculate_trend_metrics(series: pd.Series) -> Dict[str, float]:
        """
        Tính toán Tốc độ tăng trưởng (Growth Rate) và Động lực phát triển (Momentum) từ chuỗi thời gian.
        """
        if len(series) < 2:
            return {"growth_rate": 0.0, "momentum": 0.0}

        vals = series.values.astype(float)
        recent_val = vals[-1]
        prev_val = vals[-2] if vals[-2] != 0 else 1.0

        # Simple Period Growth Rate
        growth_rate = (recent_val - prev_val) / abs(prev_val)

        # Momentum: CAGR or Moving Average Differential
        if len(vals) >= 4:
            ma_short = np.mean(vals[-2:])
            ma_long = np.mean(vals[-4:])
            momentum = (ma_short - ma_long) / (ma_long if ma_long != 0 else 1.0)
        else:
            momentum = growth_rate

        return {
            "growth_rate": round(float(growth_rate), 4),
            "momentum": round(float(momentum), 4)
        }
