import pandas as pd
import numpy as np
from typing import List, Dict, Any, Tuple
import warnings

try:
    from statsmodels.tsa.arima.model import ARIMA
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    STATSMODELS_AVAILABLE = True
except ImportError:
    STATSMODELS_AVAILABLE = False


class TimeSeriesForecastModel:
    """
    Model dự báo chuỗi thời gian xu hướng công nghệ (Exponential Smoothing / ARIMA).
    """

    def __init__(self, order: Tuple[int, int, int] = (1, 1, 0)):
        self.order = order

    def forecast(
        self, 
        series: pd.Series, 
        steps: int = 3, 
        freq: str = "MS"
    ) -> List[Dict[str, Any]]:
        """
        Dự báo n bước tiếp theo trong tương lai.
        Trả về danh sách dict chứa predicted_value, lower_bound, upper_bound.
        """
        if series.empty:
            return []

        vals = series.values.astype(float)
        n = len(vals)

        # Lấy mốc thời gian cuối cùng
        if isinstance(series.index, pd.DatetimeIndex):
            last_date = series.index[-1]
        else:
            last_date = pd.Timestamp.now()

        future_dates = pd.date_range(start=last_date, periods=steps + 1, freq=freq)[1:]

        predictions = []
        lower_bounds = []
        upper_bounds = []

        # Thử nghiệm với Statsmodels ARIMA nếu đủ sample
        fit_success = False
        if STATSMODELS_AVAILABLE and n >= 4:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    model = ARIMA(vals, order=self.order)
                    fitted = model.fit()
                    forecast_res = fitted.get_forecast(steps=steps)
                    predictions = forecast_res.predicted_mean.tolist()
                    conf_int = forecast_res.conf_int(alpha=0.05)
                    lower_bounds = conf_int[:, 0].tolist()
                    upper_bounds = conf_int[:, 1].tolist()
                    fit_success = True
            except Exception:
                fit_success = False

        if not fit_success:
            # Linear trend fallback nếu dữ liệu ít hoặc ARIMA gặp lỗi
            x = np.arange(n)
            slope, intercept = np.polyfit(x, vals, 1) if n >= 2 else (0.0, vals[-1])
            std_err = np.std(vals) if n >= 2 else vals[-1] * 0.05

            for i in range(1, steps + 1):
                pred = slope * (n - 1 + i) + intercept
                pred = max(0.0, pred)
                predictions.append(pred)
                lower_bounds.append(max(0.0, pred - 1.96 * std_err))
                upper_bounds.append(pred + 1.96 * std_err)

        results = []
        for date, pred, low, high in zip(future_dates, predictions, lower_bounds, upper_bounds):
            results.append({
                "timestamp": date.strftime("%Y-%m"),
                "predicted_value": round(float(pred), 2),
                "lower_bound": round(float(max(0.0, low)), 2),
                "upper_bound": round(float(high), 2)
            })

        return results
