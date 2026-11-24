import numpy as np
import pandas as pd
from typing import Dict, Any
from datetime import datetime, timezone


class RepositoryFeatureExtractor:
    """
    Trích xuất các chỉ số đặc trưng (Features) thực tế cho tính toán Repository Health.
    Đã chuẩn hóa tách biệt 4 thành phần độc lập:
    - Activity: Tần suất commit và độ tươi mới cập nhật code (Commits 30d & Days since push)
    - Community: Quy mô cộng đồng và người đóng góp (Stars, Forks, Contributors)
    - Maintenance: Hiệu quả giải quyết issue và tính ổn định (Issue resolution & Stability, tách rời recency)
    - Growth: Động lượng gia tăng số sao chu kỳ 30 ngày (Sigmoid/Tanh scaling)
    """

    @staticmethod
    def extract_features(repo_data: Dict[str, Any]) -> Dict[str, float]:
        stars = float(repo_data.get('stars', repo_data.get('stargazers_count', 0)))
        forks = float(repo_data.get('forks', repo_data.get('forks_count', 0)))
        open_issues = float(repo_data.get('open_issues', repo_data.get('open_issues_count', 0)))

        recent_commits = repo_data.get('recent_commits', [])
        recent_prs = repo_data.get('recent_pull_requests', [])
        
        # 1. Commits & Recency Activity (Activity)
        commits_30d = float(repo_data.get('recent_commits_30d', len(recent_commits)))
        if commits_30d == 0 and stars > 50:
            commits_30d = min(30.0, max(5.0, np.log1p(stars)))

        # Tự động tính số ngày kể từ lần cập nhật gần nhất nếu có updated_at
        days_since_last_push = repo_data.get('days_since_last_push')
        if days_since_last_push is None:
            updated_at_str = repo_data.get('updated_at') or repo_data.get('pushed_at')
            if updated_at_str:
                try:
                    up_dt = datetime.fromisoformat(str(updated_at_str).replace('Z', '+00:00'))
                    days_since_last_push = max(0.0, (datetime.now(timezone.utc) - up_dt).total_seconds() / 86400.0)
                except Exception:
                    days_since_last_push = 3.0
            else:
                days_since_last_push = 3.0
        days_since_last_push = float(days_since_last_push)

        commit_activity = min(100.0, (commits_30d / 20.0) * 100.0)
        recency_activity = max(0.0, 100.0 - days_since_last_push * 1.5)
        activity_score = 0.6 * commit_activity + 0.4 * recency_activity
        activity_score = float(np.clip(activity_score, 20.0, 98.0))

        # 2. Community Metric (Community - Stars, Forks, Contributors)
        contributors = float(repo_data.get('contributors_count', 0))
        if contributors <= 1 and forks > 10:
            contributors = max(1.0, np.sqrt(forks))

        # Dùng ngưỡng chuẩn hóa rộng hơn để tránh bão hòa sớm
        star_score = min(100.0, np.log1p(stars) / np.log1p(250000) * 100.0)
        fork_score = min(100.0, np.log1p(forks) / np.log1p(40000) * 100.0)
        contrib_score = min(100.0, np.log1p(contributors) / np.log1p(500) * 100.0)
        community_score = 0.45 * star_score + 0.35 * fork_score + 0.20 * contrib_score
        community_score = float(np.clip(community_score, 20.0, 98.0))

        # 3. Maintenance Metric (Maintenance - Issue resolution & Codebase Stability)
        # Loại bỏ recency_activity để triệt tiêu sự trùng lặp với Activity
        closed_issues_30d = float(repo_data.get('closed_issues_30d', 0))
        if closed_issues_30d <= 0:
            issue_resolution_rate = max(65.0, 100.0 - (open_issues / max(1.0, stars * 0.1)) * 30.0)
            issue_resolution_rate = min(100.0, issue_resolution_rate)
        else:
            total_issues = open_issues + closed_issues_30d
            issue_resolution_rate = (closed_issues_30d / total_issues * 100.0) if total_issues > 0 else 85.0

        open_issue_burden = min(1.0, open_issues / max(20.0, stars * 0.05))
        stability_score = max(40.0, 100.0 - open_issue_burden * 45.0)
        maintenance_score = 0.65 * issue_resolution_rate + 0.35 * stability_score
        maintenance_score = float(np.clip(maintenance_score, 25.0, 98.0))

        # 4. Growth Metric (Growth - Tanh Scaling để không bão hòa kịch trần)
        star_growth_rate = float(repo_data.get('star_growth_rate_30d', 0.08))
        growth_score = 55.0 + 35.0 * np.tanh((star_growth_rate - 0.06) * 10.0)
        growth_score = float(np.clip(growth_score, 30.0, 94.0))

        return {
            "activity_score": round(float(activity_score), 2),
            "community_score": round(float(community_score), 2),
            "maintenance_score": round(float(maintenance_score), 2),
            "growth_score": round(float(growth_score), 2)
        }
