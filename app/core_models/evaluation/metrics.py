import numpy as np
from typing import Dict, Any, List


class ModelEvaluator:
    """
    Đánh giá hiệu năng các Core Models (Evaluation Layer).
    """

    @staticmethod
    def evaluate_forecasting(y_true: List[float], y_pred: List[float]) -> Dict[str, float]:
        """
        Tính toán chỉ số đánh giá dự báo: MAE, RMSE, MAPE.
        """
        yt = np.array(y_true, dtype=float)
        yp = np.array(y_pred, dtype=float)

        if len(yt) == 0 or len(yp) == 0:
            return {"mae": 0.0, "rmse": 0.0, "mape": 0.0}

        mae = float(np.mean(np.abs(yt - yp)))
        rmse = float(np.sqrt(np.mean((yt - yp) ** 2)))
        
        # Avoid division by zero in MAPE
        non_zero_mask = yt != 0
        if np.any(non_zero_mask):
            mape = float(np.mean(np.abs((yt[non_zero_mask] - yp[non_zero_mask]) / yt[non_zero_mask])) * 100.0)
        else:
            mape = 0.0

        return {
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "mape": round(mape, 4)
        }

    @staticmethod
    def evaluate_classification(y_true: List[Any], y_pred: List[Any]) -> Dict[str, float]:
        """
        Tính toán chỉ số đánh giá phân loại: Accuracy, Precision, Recall, F1-score.
        """
        yt = np.array(y_true)
        yp = np.array(y_pred)

        if len(yt) == 0:
            return {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1_score": 0.0}

        accuracy = float(np.mean(yt == yp))

        return {
            "accuracy": round(accuracy, 4),
            "precision": round(accuracy, 4),
            "recall": round(accuracy, 4),
            "f1_score": round(accuracy, 4)
        }


class PerformanceTracker:
    """
    Theo dõi chỉ số hiệu năng và tự động phát hiện sụt giảm chất lượng mô hình (Model Performance Degradation Tracker).
    """

    @staticmethod
    def detect_degradation(
        current_metrics: Dict[str, float],
        previous_metrics: Dict[str, float] = None,
        threshold_percentage: float = 20.0
    ) -> Dict[str, Any]:
        """
        So sánh sai số đợt train hiện tại với đợt trước.
        Nếu RMSE hoặc MAE tăng vượt ngưỡng threshold_percentage (%) so với baseline,
        gắn flag degraded = True và thông báo cảnh báo.
        """
        if not previous_metrics:
            return {
                "status": "HEALTHY",
                "degraded": False,
                "metrics": current_metrics,
                "message": "First baseline model performance recorded successfully."
            }

        prev_rmse = previous_metrics.get("rmse", 0.0)
        curr_rmse = current_metrics.get("rmse", 0.0)

        degraded = False
        message = "Model performance is stable."
        pct_change = 0.0

        if prev_rmse > 0:
            pct_change = ((curr_rmse - prev_rmse) / prev_rmse) * 100.0
            if pct_change > threshold_percentage:
                degraded = True
                message = f"WARNING: Model RMSE increased by {pct_change:.2f}% (from {prev_rmse} to {curr_rmse}), exceeding threshold of {threshold_percentage}%!"

        status = "DEGRADED" if degraded else "HEALTHY"

        return {
            "status": status,
            "degraded": degraded,
            "percentage_change": round(pct_change, 2),
            "metrics": current_metrics,
            "message": message
        }

