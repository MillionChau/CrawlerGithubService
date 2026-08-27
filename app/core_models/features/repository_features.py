import numpy as np
import pandas as pd
from typing import Dict, Any
from datetime import datetime


class RepositoryFeatureExtractor:
    """
    Trích xuất các chỉ số đặc trưng (Features) thực tế cho tính toán Repository Health.
    Xử lý thông minh khi dữ liệu sub-metrics bị giới hạn hoặc khuyết thiếu.
    """

    @staticmethod
    def extract_features(repo_data: Dict[str, Any]) -> Dict[str, float]:
        stars = float(repo_data.get('stars', repo_data.get('stargazers_count', 0)))
        forks = float(repo_data.get('forks', repo_data.get('forks_count', 0)))
        open_issues = float(repo_data.get('open_issues', repo_data.get('open_issues_count', 0)))

        recent_commits = repo_data.get('recent_commits', [])
        recent_prs = repo_data.get('recent_pull_requests', [])
        
        # 1. Commits & Recency Activity
        commits_30d = float(repo_data.get('recent_commits_30d', len(recent_commits)))
        if commits_30d == 0 and stars > 50:
            # Ước lượng commits dựa trên quy mô stars nếu không lấy được sub-commits
            commits_30d = min(30.0, max(5.0, np.log1p(stars)))

        days_since_last_push = float(repo_data.get('days_since_last_push', 3))
        
        commit_activity = min(100.0, (commits_30d / 20.0) * 100.0)
        recency_activity = max(0.0, 100.0 - days_since_last_push * 1.5)
        activity_score = 0.6 * commit_activity + 0.4 * recency_activity

        # 2. Community Metric (0 - 100)
        contributors = float(repo_data.get('contributors_count', 0))
        if contributors <= 1 and forks > 10:
            # Ước lượng số contributors từ số lượng forks
            contributors = max(1.0, np.sqrt(forks))

        star_score = min(100.0, np.log1p(stars) / np.log1p(50000) * 100.0)
        fork_score = min(100.0, np.log1p(forks) / np.log1p(10000) * 100.0)
        contrib_score = min(100.0, np.log1p(contributors) / np.log1p(200) * 100.0)
        community_score = 0.45 * star_score + 0.35 * fork_score + 0.20 * contrib_score

        # 3. Maintenance Metric (0 - 100)
        closed_issues_30d = float(repo_data.get('closed_issues_30d', 0))
        if closed_issues_30d <= 0:
            # Đối với các dự án lớn, số closed issues thường tương đương hoặc gấp đôi open issues
            issue_resolution_rate = max(70.0, 100.0 - (open_issues / max(1.0, stars * 0.1)) * 30.0)
            issue_resolution_rate = min(100.0, issue_resolution_rate)
        else:
            total_issues = open_issues + closed_issues_30d
            issue_resolution_rate = (closed_issues_30d / total_issues * 100.0) if total_issues > 0 else 85.0

        maintenance_score = 0.6 * issue_resolution_rate + 0.4 * recency_activity

        # 4. Growth Metric (0 - 100)
        star_growth_rate = float(repo_data.get('star_growth_rate_30d', 0.08))
        growth_score = min(100.0, max(40.0, (star_growth_rate * 400.0) + 50.0))

        return {
            "activity_score": round(float(activity_score), 2),
            "community_score": round(float(community_score), 2),
            "maintenance_score": round(float(maintenance_score), 2),
            "growth_score": round(float(growth_score), 2)
        }
