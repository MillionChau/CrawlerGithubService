from typing import Dict, Any, Optional
from app.core_models.features.language_features import LanguageFeatureExtractor


from app.core.crawl_config import CrawlConfigManager


class LanguageHealthModel:
    """
    Model đánh giá sức khỏe Ngôn ngữ Lập trình (Language Health Model).
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
        Đánh giá điểm sức khỏe của một ngôn ngữ lập trình.
        Input: metrics của ngôn ngữ lập trình
        Output: schema quy định trong SRS
        """
        language_name = lang_data.get('language', 'Unknown')
        
        metrics = self.feature_extractor.extract_features(lang_data)

        health_score = (
            metrics["repo_density_score"] * self.weights["density"] +
            metrics["popularity_score"] * self.weights["popularity"] +
            metrics["ecosystem_activity_score"] * self.weights["ecosystem"] +
            metrics["growth_momentum_score"] * self.weights["growth"]
        )

        health_score = round(float(health_score), 2)
        health_level = self.determine_health_level(health_score)

        return {
            "language": language_name,
            "health_score": health_score,
            "health_level": health_level,
            "metrics": metrics
        }
