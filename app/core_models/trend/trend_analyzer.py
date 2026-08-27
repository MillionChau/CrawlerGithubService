import pandas as pd
from typing import Dict, Any, List, Union
from app.core_models.features.trend_features import TrendFeatureExtractor


class TechnologyTrendAnalyzer:
    """
    Phân tích xu hướng phát triển công nghệ (Technology Trend Analysis).
    Xác định trạng thái: EMERGING, GROWING, STABLE, DECLINING.
    """

    def __init__(self):
        self.feature_extractor = TrendFeatureExtractor()

    def classify_trend(self, growth_rate: float, momentum: float) -> str:
        if growth_rate > 0.15 and momentum > 0.2:
            return "EMERGING"
        elif growth_rate > 0.03:
            return "GROWING"
        elif growth_rate >= -0.03:
            return "STABLE"
        else:
            return "DECLINING"

    def analyze(
        self, 
        technology: str, 
        time_series_data: Union[List[float], pd.Series, List[Dict[str, Any]]]
    ) -> Dict[str, Any]:
        """
        Phân tích chuỗi thời gian của công nghệ và xác định xu hướng.
        Input: technology name & metric values over time
        Output JSON: exact schema required by DevRadar spec.
        """
        if isinstance(time_series_data, list) and time_series_data and isinstance(time_series_data[0], dict):
            df = pd.DataFrame(time_series_data)
            metric_series = df.get('value', df.get('stars', df.get('repository_count', pd.Series([]))))
        elif isinstance(time_series_data, list):
            metric_series = pd.Series(time_series_data)
        else:
            metric_series = time_series_data

        metrics = self.feature_extractor.calculate_trend_metrics(metric_series)
        growth_rate = metrics["growth_rate"]
        momentum = metrics["momentum"]
        
        trend = self.classify_trend(growth_rate, momentum)

        return {
            "technology": technology,
            "trend": trend,
            "growth_rate": growth_rate,
            "momentum": momentum
        }
