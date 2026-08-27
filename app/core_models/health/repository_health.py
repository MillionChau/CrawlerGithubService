from typing import Dict, Any, Optional
from app.core_models.features.repository_features import RepositoryFeatureExtractor


from app.core.crawl_config import CrawlConfigManager


class RepositoryHealthModel:
    """
    Model đánh giá sức khỏe Repository (Repository Health Model) dựa trên Weighted Scoring.
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        # Trọng số có thể cấu hình động (Configurable Weights từ crawl_config.json)
        self.weights = weights or CrawlConfigManager.get_repository_health_weights()
        self.feature_extractor = RepositoryFeatureExtractor()

    def determine_health_level(self, score: float) -> str:
        if score >= 80.0:
            return "HEALTHY"
        elif score >= 60.0:
            return "MODERATE"
        elif score >= 40.0:
            return "AT_RISK"
        else:
            return "CRITICAL"

    def evaluate(self, repo_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Đánh giá điểm sức khỏe và xếp loại Repository.
        Input: repository statistics & activity metrics
        Output JSON: exact schema required by DevRadar spec.
        """
        repo_name = repo_data.get('full_name', repo_data.get('repository', 'unknown/repo'))
        
        components = self.feature_extractor.extract_features(repo_data)

        # Tính toán điểm tổng hợp có trọng số
        health_score = (
            components["activity_score"] * self.weights["activity"] +
            components["community_score"] * self.weights["community"] +
            components["maintenance_score"] * self.weights["maintenance"] +
            components["growth_score"] * self.weights["growth"]
        )

        health_score = round(float(health_score), 2)
        health_level = self.determine_health_level(health_score)

        return {
            "repository": repo_name,
            "health_score": health_score,
            "health_level": health_level,
            "components": components
        }
