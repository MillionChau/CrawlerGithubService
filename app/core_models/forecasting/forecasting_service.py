import pandas as pd
from typing import Dict, Any, List, Union
from app.core_models.forecasting.arima_model import TimeSeriesForecastModel


class ForecastingService:
    """
    Service quản lý dự báo xu hướng công nghệ (Technology Forecasting Service).
    """

    def __init__(self):
        self.forecast_model = TimeSeriesForecastModel()

    def predict_technology(
        self, 
        technology: str, 
        history_records: List[Dict[str, Any]], 
        steps: int = 3
    ) -> Dict[str, Any]:
        """
        Dự báo xu hướng công nghệ trong tương lai.
        Input: list record chứa timestamp, metric, value
        Output: schema quy định trong DevRadar SRS
        """
        if not history_records:
            return {
                "technology": technology,
                "forecast": []
            }

        df = pd.DataFrame(history_records)
        
        # Sort by timestamp
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp')

        metric_col = 'value' if 'value' in df.columns else ('repository_count' if 'repository_count' in df.columns else df.columns[-1])
        series = pd.Series(df[metric_col].values, index=df.get('timestamp', pd.RangeIndex(len(df))))

        forecast_results = self.forecast_model.forecast(series, steps=steps)

        return {
            "technology": technology,
            "forecast": forecast_results
        }
