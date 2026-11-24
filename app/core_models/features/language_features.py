import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional

# Hằng số chuẩn hóa cố định theo phiên bản V3 (Frozen Regularization Constants)
K_REPO = 50.0
K_STARS = 75000.0
FALLBACK_EPSILON = 1e-4

# Universal Reference Scale Anchors (Thang đo chuẩn hóa cố định, độc lập với snapshot)
UNIVERSAL_STAR_SHARE_MIN = 0.01
UNIVERSAL_STAR_SHARE_MAX = 35.0
UNIVERSAL_REPO_SHARE_MIN = 0.01
UNIVERSAL_REPO_SHARE_MAX = 25.0
UNIVERSAL_CADENCE_CEILING = 50.0


class LanguageFeatureExtractor:
    """
    Trích xuất đặc trưng ngôn ngữ lập trình - Đặc tả Kiến trúc V3 (Production Edition).
    Phân tách rạch ròi 3 chiều toán học & 5 nhóm nguyên tắc định lượng:
    - Stock: Market Share & Log-Market Share Popularity / Density
    - Flow: Activity Coverage (pushed_at) & Activity Intensity (commit/PR velocity)
    - Momentum: Regularized Relative Growth, Bậc thang Fallback khi MAD suy biến, New Influx & Churn Volatility
    """

    @staticmethod
    def compute_robust_z_scores(values: List[float]) -> np.ndarray:
        """
        Bậc thang Fallback (The Fallback Ladder) khi MAD suy biến:
        1. Tầng 1: Robust Z-Score bằng Median Absolute Deviation (MAD).
        2. Tầng 2: Interquartile Range (IQR) khi > 50% dữ liệu trùng Median.
        3. Tầng 3: Percentile / Rank-based Normalization khi IQR suy biến.
        4. Tầng 4: Dữ liệu thực sự đồng nhất 100% -> gán 0.0 (trung tính tuyệt đối).
        """
        arr = np.array(values, dtype=float)
        n = len(arr)
        if n <= 1:
            return np.zeros(n, dtype=float)

        med = float(np.median(arr))
        abs_dev = np.abs(arr - med)
        mad = float(1.4826 * np.median(abs_dev))

        # Tầng 1: MAD
        if mad >= FALLBACK_EPSILON:
            return (arr - med) / mad

        # Tầng 2: IQR
        q75, q25 = np.percentile(arr, [75, 25])
        iqr = float(q75 - q25)
        if iqr >= FALLBACK_EPSILON:
            return (arr - med) / (0.7413 * iqr)

        # Tầng 3: Percentile Rank
        val_range = float(np.max(arr) - np.min(arr))
        if val_range >= FALLBACK_EPSILON:
            ranks = pd.Series(arr).rank(method="average").values
            return (ranks - 1.0) / max(1.0, (n - 1.0)) * 4.0 - 2.0  # Scale [-2.0, +2.0]

        # Tầng 4: Dữ liệu hoàn toàn đồng nhất
        return np.zeros(n, dtype=float)

    @staticmethod
    def extract_features(lang_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Trích xuất đặc trưng đầy đủ theo Specification V3.
        """
        repo_count = float(lang_data.get('repository_count', 0))
        total_stars = float(lang_data.get('total_stars', 0))
        total_forks = float(lang_data.get('total_forks', 0))

        # ---------------------------------------------------------------------
        # 1. STOCK: Market Share & Log-Market Share Popularity / Density
        # ---------------------------------------------------------------------
        # Lấy hoặc nội suy Market Share (%)
        star_market_share = lang_data.get("star_market_share_pct")
        if star_market_share is None:
            rel_star = float(lang_data.get("relative_star_ratio", 0.0))
            star_market_share = rel_star * 100.0 if rel_star > 0 else (total_stars / max(1.0, total_stars * 4.0)) * 100.0
        star_market_share = float(np.clip(star_market_share, 0.0, 100.0))

        repo_market_share = lang_data.get("repo_market_share_pct")
        if repo_market_share is None:
            rel_repo = float(lang_data.get("relative_repo_ratio", 0.0))
            repo_market_share = rel_repo * 100.0 if rel_repo > 0 else (repo_count / max(1.0, repo_count * 4.0)) * 100.0
        repo_market_share = float(np.clip(repo_market_share, 0.0, 100.0))

        # Popularity Score & Density Score ánh xạ từ Universal Reference Scale
        if "popularity_score" in lang_data and lang_data["popularity_score"] is not None:
            popularity = float(lang_data["popularity_score"])
        else:
            range_share = np.log1p(UNIVERSAL_STAR_SHARE_MAX) - np.log1p(UNIVERSAL_STAR_SHARE_MIN)
            popularity = 40.0 + 55.0 * ((np.log1p(star_market_share) - np.log1p(UNIVERSAL_STAR_SHARE_MIN)) / range_share)
        popularity = float(np.clip(popularity, 25.0, 95.0))

        if "repo_density_score" in lang_data and lang_data["repo_density_score"] is not None:
            repo_density = float(lang_data["repo_density_score"])
        else:
            range_r_share = np.log1p(UNIVERSAL_REPO_SHARE_MAX) - np.log1p(UNIVERSAL_REPO_SHARE_MIN)
            repo_density = 40.0 + 55.0 * ((np.log1p(repo_market_share) - np.log1p(UNIVERSAL_REPO_SHARE_MIN)) / range_r_share)
        repo_density = float(np.clip(repo_density, 25.0, 95.0))

        # ---------------------------------------------------------------------
        # 2. FLOW: Activity Coverage & Commit Cadence Intensity
        # ---------------------------------------------------------------------
        if "ecosystem_activity_score" in lang_data and lang_data["ecosystem_activity_score"] is not None:
            ecosystem_activity = float(lang_data["ecosystem_activity_score"])
            coverage_pct = float(lang_data.get("activity_coverage_pct", 90.0))
            intensity_score = float(lang_data.get("activity_intensity_score", 85.0))
            fork_depth = float(lang_data.get("fork_depth_quality", 80.0))
        else:
            mature_count = max(1.0, float(lang_data.get("mature_repos", repo_count * 0.95)))
            act90 = float(lang_data.get("active_mature_repos_90d", lang_data.get("active_90d", 0)))
            coverage_pct = float(np.clip((act90 / mature_count) * 100.0, 0.0, 100.0))

            # Activity Intensity: Commit Cadence per mature repository
            commits_90d = float(lang_data.get("total_commits_90d", lang_data.get("activity_intensity_density", 12.0) * mature_count))
            commit_cadence = commits_90d / mature_count
            intensity_score = 30.0 + 65.0 * (np.log1p(commit_cadence) / np.log1p(UNIVERSAL_CADENCE_CEILING))
            intensity_score = float(np.clip(intensity_score, 25.0, 95.0))

            # Fork-to-Star depth quality (Community Utility)
            fork_ratio = total_forks / max(1.0, total_stars) if total_stars > 0 else 0.15
            depth_ratio = min(1.0, fork_ratio / 0.18)
            fork_depth = 40.0 + depth_ratio * 55.0

            ecosystem_activity = 0.50 * coverage_pct + 0.35 * intensity_score + 0.15 * fork_depth
        ecosystem_activity = float(np.clip(ecosystem_activity, 25.0, 95.0))

        # ---------------------------------------------------------------------
        # 3. MOMENTUM: Regularized Growth, Volatility & Insufficient History
        # ---------------------------------------------------------------------
        growth_status = str(lang_data.get("growth_status", "VALID"))
        raw_growth_score = lang_data.get("growth_momentum_score")

        if growth_status == "INSUFFICIENT_HISTORY" or (raw_growth_score is None and "growth_momentum_score" not in lang_data and "repo_growth_rate" not in lang_data):
            growth_momentum = None
            growth_status = "INSUFFICIENT_HISTORY"
            reg_repo_growth_pct = 0.0
            reg_star_growth_pct = 0.0
            new_influx_pct = 0.0
            churn_pct = 0.0
        else:
            if raw_growth_score is not None:
                growth_momentum = float(raw_growth_score)
            else:
                # Regularized Delta calculation
                r_rate = float(lang_data.get("repo_growth_rate", 0.05))
                s_rate = float(lang_data.get("star_growth_rate", 0.06))
                combined = 0.50 * r_rate + 0.50 * s_rate
                growth_momentum = 50.0 + 35.0 * np.tanh((combined - 0.06) * 10.0)
            growth_momentum = float(np.clip(growth_momentum, 15.0, 85.0))
            growth_status = "VALID"
            reg_repo_growth_pct = round(float(lang_data.get("repo_growth_rate", 0.05)) * 100.0, 2)
            reg_star_growth_pct = round(float(lang_data.get("star_growth_rate", 0.06)) * 100.0, 2)
            new_influx_pct = round(float(lang_data.get("new_influx_rate_pct", 2.0)), 2)
            churn_pct = round(float(lang_data.get("churn_rate_pct", 0.8)), 2)

        # ---------------------------------------------------------------------
        # 4. CONFIDENCE SCORE (0.0 - 1.0)
        # ---------------------------------------------------------------------
        # Phụ thuộc vào cỡ mẫu (N >= 30), tính liên tục của lịch sử, độ tương đồng cohort
        conf = 1.0
        if repo_count < 10:
            conf *= 0.40
        elif repo_count < 30:
            conf *= 0.65
        elif repo_count < 100:
            conf *= 0.85

        if growth_status == "INSUFFICIENT_HISTORY":
            conf *= 0.70

        jaccard_overlap = float(lang_data.get("jaccard_similarity", 1.0))
        if jaccard_overlap < 0.60:
            conf *= 0.75

        confidence_score = round(float(np.clip(conf, 0.20, 1.0)), 2)
        confidence_level = "HIGH" if confidence_score >= 0.80 else ("MEDIUM" if confidence_score >= 0.55 else "LOW")

        # ---------------------------------------------------------------------
        # 5. CẤU TRÚC SUB-METRICS TÁCH BIỆT (Specification V3 Schema)
        # ---------------------------------------------------------------------
        absolute_metrics = {
            "repository_count": int(repo_count),
            "total_stars": int(total_stars),
            "total_forks": int(total_forks),
            "active_mature_repos_90d": int(lang_data.get("active_90d", int(repo_count * 0.95))),
            "infant_repos_30d": int(lang_data.get("infant_repos_30d", max(1, int(repo_count * 0.03))))
        }

        relative_market_metrics = {
            "star_market_share_pct": round(star_market_share, 2),
            "repo_market_share_pct": round(repo_market_share, 2),
            "popularity_score": round(popularity, 2),
            "density_score": round(repo_density, 2)
        }

        flow_metrics = {
            "activity_coverage_pct": round(coverage_pct, 2),
            "activity_intensity_score": round(intensity_score, 2),
            "fork_depth_quality": round(fork_depth, 2),
            "flow_score": round(ecosystem_activity, 2)
        }

        momentum_metrics = {
            "status": growth_status,
            "regularized_repo_growth_pct": reg_repo_growth_pct,
            "regularized_star_growth_pct": reg_star_growth_pct,
            "new_influx_rate_pct": new_influx_pct,
            "churn_rate_pct": churn_pct,
            "migration_net_flow": int(lang_data.get("migration_net_flow", 0)),
            "growth_momentum_score": round(growth_momentum, 2) if growth_momentum is not None else None
        }

        # Dict metrics tương thích ngược cho các API cũ
        compat_metrics = {
            "repo_density_score": round(repo_density, 2),
            "popularity_score": round(popularity, 2),
            "ecosystem_activity_score": round(ecosystem_activity, 2),
            "growth_momentum_score": round(growth_momentum, 2) if growth_momentum is not None else 50.0
        }

        return {
            "repo_density_score": round(repo_density, 2),
            "popularity_score": round(popularity, 2),
            "ecosystem_activity_score": round(ecosystem_activity, 2),
            "growth_momentum_score": round(growth_momentum, 2) if growth_momentum is not None else None,
            "confidence_score": confidence_score,
            "confidence_level": confidence_level,
            "growth_status": growth_status,
            "absolute_metrics": absolute_metrics,
            "relative_market_metrics": relative_market_metrics,
            "flow_metrics": flow_metrics,
            "momentum_metrics": momentum_metrics,
            "metrics": compat_metrics
        }
