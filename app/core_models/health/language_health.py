from typing import Dict, Any, Optional
from app.core_models.features.language_features import LanguageFeatureExtractor
from app.core.crawl_config import CrawlConfigManager


class LanguageHealthModel:
    """
    Model đánh giá sức khỏe Ngôn ngữ Lập trình (Language Health Model) - Specification V3.
    Hỗ trợ tái phân bổ trọng số khi thiếu dữ liệu lịch sử (INSUFFICIENT_HISTORY)
    và xuất đầy đủ schema phân rã các chiều Stock, Flow, Momentum kèm Confidence Score.
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or CrawlConfigManager.get_language_health_weights()
        self.feature_extractor = LanguageFeatureExtractor()

    def determine_health_level(self, score: float) -> str:
        if score >= 80.0:
            return "HEALTHY"
        elif score >= 60.0:
            return "MODERATE"
        elif score >= 40.0:
            return "AT_RISK"
        else:
            return "CRITICAL"

    def evaluate(self, lang_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Đánh giá điểm sức khỏe của một ngôn ngữ lập trình theo Specification V3.
        """
        language_name = lang_data.get('language', 'Unknown')
        
        extracted = self.feature_extractor.extract_features(lang_data)

        density = extracted["repo_density_score"]
        popularity = extracted["popularity_score"]
        ecosystem = extracted["ecosystem_activity_score"]
        growth = extracted["growth_momentum_score"]

        # Nếu không đủ dữ liệu lịch sử tăng trưởng, tái phân bổ trọng số cho Stock và Flow
        if growth is None:
            base_weights = self.weights["density"] + self.weights["popularity"] + self.weights["ecosystem"]
            health_score = (
                density * self.weights["density"] +
                popularity * self.weights["popularity"] +
                ecosystem * self.weights["ecosystem"]
            ) / max(1e-5, base_weights)
        else:
            health_score = (
                density * self.weights["density"] +
                popularity * self.weights["popularity"] +
                ecosystem * self.weights["ecosystem"] +
                growth * self.weights["growth"]
            )

        health_score = round(float(health_score), 2)
        health_level = self.determine_health_level(health_score)

        return {
            "language": language_name,
            "health_score": health_score,
            "health_level": health_level,
            "confidence_score": extracted.get("confidence_score", 0.90),
            "confidence_level": extracted.get("confidence_level", "HIGH"),
            "growth_status": extracted.get("growth_status", "VALID"),
            "metrics": extracted.get("metrics", {
                "repo_density_score": density,
                "popularity_score": popularity,
                "ecosystem_activity_score": ecosystem,
                "growth_momentum_score": growth if growth is not None else 50.0
            }),
            "absolute_metrics": extracted.get("absolute_metrics", {}),
            "relative_market_metrics": extracted.get("relative_market_metrics", {}),
            "flow_metrics": extracted.get("flow_metrics", {}),
            "momentum_metrics": extracted.get("momentum_metrics", {})
        }
