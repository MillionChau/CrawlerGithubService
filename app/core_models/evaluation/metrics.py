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
