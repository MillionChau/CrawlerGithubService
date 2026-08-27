import numpy as np
import pandas as pd
from typing import Dict, Any


class LanguageFeatureExtractor:
    """
    Trích xuất đặc trưng ngôn ngữ lập trình từ tập dữ liệu tập hợp các repositories.
    """

    @staticmethod
    def extract_features(lang_data: Dict[str, Any]) -> Dict[str, float]:
        """
        Trích xuất các chỉ số đặc trưng cho ngôn ngữ lập trình.
        """
        repo_count = float(lang_data.get('repository_count', 0))
        total_stars = float(lang_data.get('total_stars', 0))
        total_forks = float(lang_data.get('total_forks', 0))
        commit_activity = float(lang_data.get('commit_activity_index', 50))
        contributor_activity = float(lang_data.get('contributor_activity_index', 50))
        repo_growth_rate = float(lang_data.get('repo_growth_rate', 0.05))
        star_growth_rate = float(lang_data.get('star_growth_rate', 0.08))

        repo_density = min(100.0, np.log1p(repo_count) / np.log1p(100000) * 100.0)
        popularity = min(100.0, np.log1p(total_stars) / np.log1p(1000000) * 100.0)
        ecosystem_activity = (commit_activity * 0.5) + (contributor_activity * 0.5)
        growth_momentum = min(100.0, max(0.0, (repo_growth_rate + star_growth_rate) * 250.0 + 50.0))

        return {
            "repo_density_score": round(float(repo_density), 2),
            "popularity_score": round(float(popularity), 2),
            "ecosystem_activity_score": round(float(ecosystem_activity), 2),
            "growth_momentum_score": round(float(growth_momentum), 2)
        }
