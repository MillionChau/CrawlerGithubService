import datetime

class MetricsCalculator:
    @staticmethod
    def calculate_health_score(repo_data: dict, activity_data: dict, structure_data: dict) -> dict:
        """
        Calculate health scores based on gathered data.
        Returns a dict of scores (0-100).
        """
        # Activity Score
        commits = activity_data.get("commits", [])
        commit_count = len(commits)
        activity_score = min(commit_count * 10, 100) # Simple metric: 10 points per recent commit
        
        # Maintenance Score
        issues = activity_data.get("issues", [])
        prs = activity_data.get("pulls", [])
        closed_issues = sum(1 for i in issues if i.get("state") == "closed")
        maintenance_score = 50.0
        if len(issues) > 0:
            maintenance_score = (closed_issues / len(issues)) * 100
            
        # Community Score
        contributors = repo_data.get("contributors", [])
        forks = repo_data.get("forks", 0)
        community_score = min(len(contributors) * 5 + forks * 0.1, 100)
        
        # Quality Score
        quality_score = 0
        if structure_data.get("has_src"): quality_score += 20
        if structure_data.get("has_test"): quality_score += 30
        if structure_data.get("has_docs"): quality_score += 20
        if structure_data.get("has_cicd"): quality_score += 30
        
        # Total Health Score
        health_score = (activity_score * 0.3) + (maintenance_score * 0.3) + (community_score * 0.2) + (quality_score * 0.2)
        
        return {
            "activity_score": round(activity_score, 2),
            "maintenance_score": round(maintenance_score, 2),
            "community_score": round(community_score, 2),
            "quality_score": round(quality_score, 2),
            "health_score": round(health_score, 2)
        }
