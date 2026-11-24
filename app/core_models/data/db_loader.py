import os
import re
import json
import time
import logging
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional
from app.db.mongo import mongo_client

logger = logging.getLogger(__name__)


class DatabaseDataLoader:
    """
    Module tải và tiền xử lý dữ liệu repositories thực tế từ MongoDB Atlas
    phục vụ cho việc Train / Evaluate các Core Models.
    """

    _language_summary_cache: Optional[List[Dict[str, Any]]] = None
    _language_summary_cache_time: float = 0.0
    _CACHE_TTL: float = 300.0  # 5 phút cache in-memory

    @staticmethod
    async def load_repositories_from_mongo() -> List[Dict[str, Any]]:
        """Tải toàn bộ repositories từ MongoDB Atlas (hỗ trợ cả Motor async & PyMongo sync)."""
        repos = []
        mongo_client.connect()

        if mongo_client.db is not None:
            try:
                cursor = mongo_client.db["repositories"].find({})
                async for doc in cursor:
                    doc["_id"] = str(doc.get("_id"))
                    repos.append(doc)
                logger.info(f"Loaded {len(repos)} repositories from MongoDB Atlas (Async).")
            except Exception as e:
                logger.warning(f"Error loading from Async MongoDB: {e}")

        if not repos and mongo_client.sync_db is not None:
            try:
                cursor = mongo_client.sync_db["repositories"].find({})
                for doc in cursor:
                    doc["_id"] = str(doc.get("_id"))
                    repos.append(doc)
                logger.info(f"Loaded {len(repos)} repositories from MongoDB Atlas (Sync).")
            except Exception as e:
                logger.warning(f"Error loading from Sync MongoDB: {e}")

        return repos

    @staticmethod
    def load_repositories_from_json(filepath: str = "crawled_data.json") -> List[Dict[str, Any]]:
        """Tải dữ liệu repositories từ file JSON local dự phòng."""
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logger.info(f"Loaded {len(data)} repositories from '{filepath}'.")
                    return data
            except Exception as e:
                logger.error(f"Error reading {filepath}: {e}")
        return []

    @classmethod
    async def get_all_repositories(cls) -> List[Dict[str, Any]]:
        """Lấy dữ liệu ưu tiên từ MongoDB Atlas, nếu rỗng thì fallback sang crawled_data.json."""
        repos = await cls.load_repositories_from_mongo()
        if not repos:
            repos = cls.load_repositories_from_json()
        return repos

    @classmethod
    async def get_language_summary(cls) -> List[Dict[str, Any]]:
        """
        Tổng hợp dữ liệu thực tế theo ngôn ngữ lập trình từ MongoDB Atlas.
        Áp dụng Dynamic Ecosystem Normalization:
        - Chuẩn hóa động Stock (Density & Popularity) theo phân phối Log-Min-Max của hệ sinh thái
        - Đo lường Flow (Ecosystem Activity) dựa trên tỷ lệ tươi mới (active trong 30d/90d) và Fork quality
        - Đo lường Momentum (Growth) bằng vận tốc gia tăng và hàm Sigmoid/Tanh, không bị trùng lặp với Activity
        """
        now = time.time()
        if cls._language_summary_cache is not None and (now - cls._language_summary_cache_time < cls._CACHE_TTL):
            return cls._language_summary_cache

        mongo_client.connect()

        # 1. Thử aggregation trực tiếp trên MongoDB Atlas để giảm tải tối đa I/O mạng
        if mongo_client.db is not None:
            try:
                from datetime import datetime, timezone, timedelta
                from app.core_models.features.language_features import (
                    LanguageFeatureExtractor,
                    K_REPO,
                    K_STARS,
                    UNIVERSAL_STAR_SHARE_MIN,
                    UNIVERSAL_STAR_SHARE_MAX,
                    UNIVERSAL_REPO_SHARE_MIN,
                    UNIVERSAL_REPO_SHARE_MAX,
                    UNIVERSAL_CADENCE_CEILING
                )
                now_utc = datetime.now(timezone.utc)
                today_str = now_utc.strftime("%Y-%m-%d")
                d30_created = (now_utc - timedelta(days=30)).strftime("%Y-%m-%d")
                d90_pushed = (now_utc - timedelta(days=90)).strftime("%Y-%m-%d")

                unwanted = [None, "", "Unknown", "Jupyter Notebook", "Shell", "HTML", "Markdown", "Dockerfile", "Batchfile", "Makefile", "TeX"]
                pipeline = [
                    {"$match": {
                        "primary_language": {"$nin": unwanted},
                        "$or": [{"stars": {"$gte": 3}}, {"forks": {"$gte": 1}}],
                        "is_fork": {"$ne": True},
                        "is_archived": {"$ne": True}
                    }},
                    {"$group": {
                        "_id": "$primary_language",
                        "repository_count": {"$sum": 1},
                        "total_stars": {"$sum": {"$ifNull": ["$stars", 0]}},
                        "total_forks": {"$sum": {"$ifNull": ["$forks", 0]}},
                        "mature_repos": {
                            "$sum": {
                                "$cond": [
                                    {
                                        "$or": [
                                            {"$eq": ["$is_mature", True]},
                                            {"$lte": [{"$ifNull": ["$created_at", d30_created]}, d30_created]}
                                        ]
                                    },
                                    1,
                                    0
                                ]
                            }
                        },
                        "infant_repos": {
                            "$sum": {
                                "$cond": [
                                    {
                                        "$and": [
                                            {"$ne": ["$is_mature", True]},
                                            {"$gt": [{"$ifNull": ["$created_at", d30_created]}, d30_created]}
                                        ]
                                    },
                                    1,
                                    0
                                ]
                            }
                        },
                        # Tử số Coverage: BẮT BUỘC chỉ đếm trên Mature Repos có commit hoặc push trong 90 ngày
                        "active_mature_repos_90d": {
                            "$sum": {
                                "$cond": [
                                    {
                                        "$and": [
                                            {
                                                "$or": [
                                                    {"$eq": ["$is_mature", True]},
                                                    {"$lte": [{"$ifNull": ["$created_at", d30_created]}, d30_created]}
                                                ]
                                            },
                                            {
                                                "$or": [
                                                    {"$eq": ["$activity_stats.has_commit_90d", True]},
                                                    {"$gte": [{"$ifNull": ["$pushed_at", "$updated_at"]}, d90_pushed]}
                                                ]
                                            }
                                        ]
                                    },
                                    1,
                                    0
                                ]
                            }
                        },
                        # Tổng số commit 90 ngày trên mature repos phục vụ tính Commit Cadence
                        "total_commits_90d": {
                            "$sum": {
                                "$cond": [
                                    {
                                        "$or": [
                                            {"$eq": ["$is_mature", True]},
                                            {"$lte": [{"$ifNull": ["$created_at", d30_created]}, d30_created]}
                                        ]
                                    },
                                    {"$ifNull": ["$activity_stats.commits_90d", 3]},
                                    0
                                ]
                            }
                        },
                        "sample_repo_ids": {"$push": "$id"}
                    }},
                    {"$sort": {"total_stars": -1}}
                ]
                cursor = mongo_client.db["repositories"].aggregate(pipeline)
                agg_results = await cursor.to_list(length=150)
                if agg_results:
                    total_eco_stars = max(1.0, float(sum(r.get("total_stars", 0) for r in agg_results)))
                    total_eco_repos = max(1.0, float(sum(r.get("repository_count", 0) for r in agg_results)))

                    # Lấy snapshot trước đó để tính regularized growth & Jaccard
                    distinct_dates = await mongo_client.db["language_health_evaluations"].distinct("snapshot_date")
                    prior_dates = [d for d in distinct_dates if d < today_str]
                    prev_date = max(prior_dates) if prior_dates else None

                    prev_lang_map = {}
                    if prev_date:
                        cursor_p = mongo_client.db["language_health_evaluations"].find({"snapshot_date": prev_date})
                        prev_docs = await cursor_p.to_list(length=300)
                        for pd in prev_docs:
                            prev_lang_map[pd["language"]] = pd

                    intermediate = []
                    momentum_signals = []

                    # Universal log ranges
                    log_range_s = np.log1p(UNIVERSAL_STAR_SHARE_MAX) - np.log1p(UNIVERSAL_STAR_SHARE_MIN)
                    log_range_r = np.log1p(UNIVERSAL_REPO_SHARE_MAX) - np.log1p(UNIVERSAL_REPO_SHARE_MIN)

                    for r in agg_results:
                        lang = r["_id"]
                        count = r.get("repository_count", 0)
                        stars = r.get("total_stars", 0)
                        forks = r.get("total_forks", 0)
                        mature = max(1, r.get("mature_repos", count))
                        infant = r.get("infant_repos", 0)
                        act90 = r.get("active_mature_repos_90d", 0)
                        total_commits = r.get("total_commits_90d", mature * 3)

                        star_share = (stars / total_eco_stars) * 100.0
                        repo_share = (count / total_eco_repos) * 100.0

                        # 1. STOCK (Universal Scale)
                        pop_score = 40.0 + 55.0 * ((np.log1p(star_share) - np.log1p(UNIVERSAL_STAR_SHARE_MIN)) / log_range_s)
                        pop_score = float(np.clip(pop_score, 25.0, 95.0))

                        dense_score = 40.0 + 55.0 * ((np.log1p(repo_share) - np.log1p(UNIVERSAL_REPO_SHARE_MIN)) / log_range_r)
                        dense_score = float(np.clip(dense_score, 25.0, 95.0))

                        # 2. FLOW (Coverage, Cadence Intensity & Fork Utility)
                        coverage_pct = min(100.0, (act90 / mature) * 100.0)
                        commit_cadence = total_commits / mature
                        intensity_score = 30.0 + 65.0 * (np.log1p(commit_cadence) / np.log1p(UNIVERSAL_CADENCE_CEILING))
                        intensity_score = float(np.clip(intensity_score, 25.0, 95.0))

                        fork_ratio = forks / max(1.0, stars) if stars > 0 else 0.0
                        fork_depth_quality = 40.0 + min(1.0, fork_ratio / 0.18) * 55.0
                        flow_score = float(np.clip(0.50 * coverage_pct + 0.35 * intensity_score + 0.15 * fork_depth_quality, 25.0, 95.0))

                        # 3. MOMENTUM & COHORT PROVENANCE
                        curr_ids = set(r.get("sample_repo_ids") or [])
                        prev_rec = prev_lang_map.get(lang)
                        if prev_rec:
                            prev_r = float(prev_rec.get("repository_count", count))
                            prev_s = float(prev_rec.get("total_stars", stars))
                            raw_r_growth_pct = round(((count - prev_r) / max(1.0, prev_r)) * 100.0, 2)
                            raw_s_growth_pct = round(((stars - prev_s) / max(1.0, prev_s)) * 100.0, 2)
                            composite_raw_mom_pct = round(0.50 * raw_r_growth_pct + 0.50 * raw_s_growth_pct, 2)

                            delta_r = (count - prev_r) / (prev_r + K_REPO)
                            delta_s = (stars - prev_s) / (prev_s + K_STARS)
                            g_status = "VALID"
                            raw_mom = 0.50 * delta_r + 0.50 * delta_s

                            prev_ids = set(prev_rec.get("sample_repo_ids") or prev_rec.get("cohort", {}).get("sample_repo_ids") or [])
                            if prev_ids:
                                common_count = len(curr_ids & prev_ids)
                                union_count = len(curr_ids | prev_ids)
                                jaccard = round(common_count / max(1, union_count), 3)
                                newly_added = len(curr_ids - prev_ids)
                                exited = len(prev_ids - curr_ids)
                            else:
                                jaccard = 1.0
                                common_count = count
                                newly_added = 0
                                exited = 0
                        else:
                            raw_r_growth_pct = 0.0
                            raw_s_growth_pct = 0.0
                            composite_raw_mom_pct = 0.0
                            delta_r = 0.0
                            delta_s = 0.0
                            g_status = "INSUFFICIENT_HISTORY"
                            raw_mom = 0.0
                            jaccard = 1.0
                            common_count = count
                            newly_added = 0
                            exited = 0

                        # 4. CONFIDENCE SCORE
                        conf = 1.0
                        if count < 10:
                            conf *= 0.40
                        elif count < 30:
                            conf *= 0.65
                        elif count < 100:
                            conf *= 0.85

                        if g_status == "INSUFFICIENT_HISTORY":
                            conf *= 0.70

                        if jaccard < 0.60:
                            conf *= 0.75

                        confidence_score = round(float(np.clip(conf, 0.20, 1.0)), 2)
                        confidence_level = "HIGH" if confidence_score >= 0.80 else ("MEDIUM" if confidence_score >= 0.55 else "LOW")

                        intermediate.append({
                            "language": lang,
                            "repository_count": count,
                            "total_stars": stars,
                            "total_forks": forks,
                            "mature_repos": mature,
                            "infant_repos": infant,
                            "active_90d": act90,
                            "star_market_share_pct": round(star_share, 4),
                            "repo_market_share_pct": round(repo_share, 4),
                            "repo_density_score": round(dense_score, 2),
                            "popularity_score": round(pop_score, 2),
                            "coverage_pct": round(coverage_pct, 2),
                            "intensity_score": round(intensity_score, 2),
                            "fork_depth_quality": round(fork_depth_quality, 2),
                            "flow_score": round(flow_score, 2),
                            "raw_repo_growth_pct": raw_r_growth_pct,
                            "raw_star_growth_pct": raw_s_growth_pct,
                            "composite_raw_momentum_pct": composite_raw_mom_pct,
                            "delta_r": delta_r,
                            "delta_s": delta_s,
                            "growth_status": g_status,
                            "raw_mom": raw_mom,
                            "jaccard_similarity": jaccard,
                            "common_repos_count": common_count,
                            "newly_added_repos_count": newly_added,
                            "exited_repos_count": exited,
                            "confidence_score": confidence_score,
                            "confidence_level": confidence_level,
                            "sample_repo_ids": list(curr_ids)[:100]
                        })
                        momentum_signals.append(raw_mom)

                    # Áp dụng Bậc thang Fallback (The Fallback Ladder)
                    z_scores = LanguageFeatureExtractor.compute_robust_z_scores(momentum_signals)

                    results = []
                    for idx, item in enumerate(intermediate):
                        lang = item["language"]
                        dense_score = item["repo_density_score"]
                        pop_score = item["popularity_score"]
                        flow_score = item["flow_score"]

                        if item["growth_status"] == "INSUFFICIENT_HISTORY":
                            growth_score = None
                            # Dynamic Rebalancing: Stock 40% (15+25) + Flow 35%
                            health_score = round((0.15 * dense_score + 0.25 * pop_score + 0.35 * flow_score) / 0.75, 2)
                        else:
                            z = z_scores[idx]
                            growth_score = float(np.clip(50.0 + 35.0 * np.tanh(z / 2.0), 15.0, 85.0))
                            # V3 Balanced Weights: 15% Density + 25% Popularity + 35% Flow + 25% Growth
                            health_score = round(0.15 * dense_score + 0.25 * pop_score + 0.35 * flow_score + 0.25 * growth_score, 2)

                        health_level = (
                            "HEALTHY" if health_score >= 80.0
                            else "MODERATE" if health_score >= 60.0
                            else "AT_RISK" if health_score >= 40.0
                            else "CRITICAL"
                        )

                        results.append({
                            "language": lang,
                            "health_score": health_score,
                            "health_level": health_level,
                            "confidence_score": item["confidence_score"],
                            "confidence_level": item["confidence_level"],
                            "repository_count": int(item["repository_count"]),
                            "total_stars": int(item["total_stars"]),
                            "total_forks": int(item["total_forks"]),
                            "active_90d": int(item["active_90d"]),
                            "infant_repos_30d": int(item["infant_repos"]),
                            "star_market_share_pct": item["star_market_share_pct"],
                            "repo_market_share_pct": item["repo_market_share_pct"],
                            "repo_density_score": dense_score,
                            "popularity_score": pop_score,
                            "ecosystem_activity_score": flow_score,
                            "growth_momentum_score": round(float(growth_score), 2) if growth_score is not None else None,
                            "growth_status": item["growth_status"],
                            "activity_coverage_pct": item["coverage_pct"],
                            "activity_intensity_score": item["intensity_score"],
                            "fork_depth_quality": item["fork_depth_quality"],
                            "repo_growth_rate": round(float(item["delta_r"]), 4),
                            "star_growth_rate": round(float(item["delta_s"]), 4),
                            "raw_repo_growth_pct": item["raw_repo_growth_pct"],
                            "raw_star_growth_pct": item["raw_star_growth_pct"],
                            "composite_raw_momentum_pct": item["composite_raw_momentum_pct"],
                            "jaccard_similarity": item["jaccard_similarity"],
                            "common_repos_count": item["common_repos_count"],
                            "newly_added_repos_count": item["newly_added_repos_count"],
                            "exited_repos_count": item["exited_repos_count"],
                            "sample_repo_ids": item["sample_repo_ids"],
                            "commit_activity_index": flow_score,
                            "contributor_activity_index": item["fork_depth_quality"],
                            # Specification V3 Nested Schema
                            "stock": {
                                "repository_count": int(item["repository_count"]),
                                "total_stars": int(item["total_stars"]),
                                "total_forks": int(item["total_forks"]),
                                "repo_market_share_pct": item["repo_market_share_pct"],
                                "star_market_share_pct": item["star_market_share_pct"],
                                "density_score": dense_score,
                                "popularity_score": pop_score
                            },
                            "flow": {
                                "mature_repos": int(item["mature_repos"]),
                                "infant_repos": int(item["infant_repos"]),
                                "active_mature_repos_90d": int(item["active_90d"]),
                                "activity_coverage_pct": item["coverage_pct"],
                                "total_commits_90d": int(item.get("total_commits_90d", item["mature_repos"] * 3)),
                                "commit_cadence": round(item.get("total_commits_90d", item["mature_repos"] * 3) / max(1, item["mature_repos"]), 2),
                                "activity_intensity_score": item["intensity_score"],
                                "fork_depth_quality": item["fork_depth_quality"],
                                "flow_score": flow_score
                            },
                            "momentum": {
                                "status": item["growth_status"],
                                "raw_metrics": {
                                    "raw_repo_growth_pct": item["raw_repo_growth_pct"],
                                    "raw_star_growth_pct": item["raw_star_growth_pct"],
                                    "composite_raw_momentum_pct": item["composite_raw_momentum_pct"]
                                },
                                "regularized_metrics": {
                                    "reg_repo_growth": round(float(item["delta_r"]), 4),
                                    "reg_star_growth": round(float(item["delta_s"]), 4),
                                    "composite_reg_momentum": round(float(item["raw_mom"]), 4)
                                },
                                "peer_distribution": {
                                    "robust_z_score": round(float(z_scores[idx]), 3),
                                    "growth_momentum_score": round(float(growth_score), 2) if growth_score is not None else None
                                }
                            },
                            "cohort": {
                                "previous_snapshot_date": prev_date,
                                "common_repos_count": item["common_repos_count"],
                                "newly_added_repos_count": item["newly_added_repos_count"],
                                "exited_repos_count": item["exited_repos_count"],
                                "jaccard_similarity": item["jaccard_similarity"]
                            }
                        })

                    cls._language_summary_cache = results
                    cls._language_summary_cache_time = now
                    return results
            except Exception as e:
                logger.warning(f"Error in MongoDB aggregation for language summary: {e}")

        # 2. Fallback sang tính toán DataFrame qua pandas nếu aggregation không khả dụng
        repos = await cls.get_all_repositories()
        if not repos:
            return []

        df = pd.DataFrame(repos)
        if 'primary_language' not in df.columns:
            return []

        df['primary_language'] = df['primary_language'].fillna('Unknown')
        df['stars'] = pd.to_numeric(df['stars'], errors='coerce').fillna(0)
        df['forks'] = pd.to_numeric(df['forks'], errors='coerce').fillna(0)
        df['open_issues'] = pd.to_numeric(df['open_issues'], errors='coerce').fillna(0)

        # Gom nhóm tính toán các chỉ số thống kê thực tế
        grouped = df.groupby('primary_language').agg(
            repository_count=('id', 'count'),
            total_stars=('stars', 'sum'),
            total_forks=('forks', 'sum'),
            avg_stars=('stars', 'mean'),
            avg_forks=('forks', 'mean')
        ).reset_index()

        grouped = grouped.rename(columns={'primary_language': 'language'})
        max_repos = grouped['repository_count'].max()
        min_repos = max(1, grouped['repository_count'].min())
        max_stars = grouped['total_stars'].max()
        min_stars = max(10, grouped['total_stars'].min())

        log_range_repos = max(1e-5, np.log1p(max_repos) - np.log1p(min_repos))
        log_range_stars = max(1e-5, np.log1p(max_stars) - np.log1p(min_stars))

        results = []
        for _, row in grouped.iterrows():
            lang = row['language']
            count = row['repository_count']
            stars = row['total_stars']
            forks = row['total_forks']

            density_score = 40.0 + 55.0 * ((np.log1p(count) - np.log1p(min_repos)) / log_range_repos)
            popularity_score = 42.0 + 53.0 * ((np.log1p(stars) - np.log1p(min_stars)) / log_range_stars)
            fork_ratio = forks / max(1.0, stars) if stars > 0 else 0.15
            depth_quality = min(1.0, fork_ratio / 0.18)
            activity_score = 75.0 + depth_quality * 15.0
            growth_score = 65.0

            results.append({
                "language": lang,
                "repository_count": int(count),
                "total_stars": int(stars),
                "total_forks": int(forks),
                "repo_density_score": round(float(density_score), 2),
                "popularity_score": round(float(popularity_score), 2),
                "ecosystem_activity_score": round(float(activity_score), 2),
                "growth_momentum_score": round(float(growth_score), 2),
                "commit_activity_index": round(float(activity_score), 2),
                "contributor_activity_index": round(float(depth_quality * 100.0), 2),
                "repo_growth_rate": 0.06,
                "star_growth_rate": 0.08
            })

        cls._language_summary_cache = results
        cls._language_summary_cache_time = now
        return results

    @classmethod
    async def save_repository_health_evaluations(cls, evaluations: List[Dict[str, Any]]) -> int:
        """Lưu danh sách kết quả đánh giá Repository Health vào MongoDB Atlas kèm timestamp lịch sử."""
        if not evaluations:
            return 0
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        iso_str = now_utc.isoformat()
        date_str = now_utc.strftime("%Y-%m-%d")

        docs = []
        for eval_item in evaluations:
            item_copy = dict(eval_item)
            item_copy["evaluated_at"] = iso_str
            item_copy["snapshot_date"] = date_str
            docs.append(item_copy)

        mongo_client.connect()
        inserted_count = 0

        if mongo_client.db is not None:
            try:
                res = await mongo_client.db["repo_health_evaluations"].insert_many(docs)
                inserted_count = len(res.inserted_ids)
                logger.info(f"Saved {inserted_count} repo health evaluation snapshots to Async MongoDB.")
            except Exception as e:
                logger.warning(f"Async Mongo insert error: {e}")

        if inserted_count == 0 and mongo_client.sync_db is not None:
            try:
                res = mongo_client.sync_db["repo_health_evaluations"].insert_many(docs)
                inserted_count = len(res.inserted_ids)
                logger.info(f"Saved {inserted_count} repo health evaluation snapshots to Sync MongoDB.")
            except Exception as e:
                logger.warning(f"Sync Mongo insert error: {e}")

        return inserted_count

    @classmethod
    async def save_language_health_evaluations(cls, evaluations: List[Dict[str, Any]]) -> int:
        """Lưu danh sách kết quả đánh giá Language Health vào MongoDB Atlas kèm timestamp lịch sử."""
        if not evaluations:
            return 0
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        iso_str = now_utc.isoformat()
        date_str = now_utc.strftime("%Y-%m-%d")

        docs = []
        for eval_item in evaluations:
            item_copy = dict(eval_item)
            item_copy["evaluated_at"] = iso_str
            item_copy["snapshot_date"] = date_str
            docs.append(item_copy)

        mongo_client.connect()
        inserted_count = 0

        if mongo_client.db is not None:
            try:
                res = await mongo_client.db["language_health_evaluations"].insert_many(docs)
                inserted_count = len(res.inserted_ids)
                logger.info(f"Saved {inserted_count} language health evaluation snapshots to Async MongoDB.")
            except Exception as e:
                logger.warning(f"Async Mongo insert error: {e}")

        if inserted_count == 0 and mongo_client.sync_db is not None:
            try:
                res = mongo_client.sync_db["language_health_evaluations"].insert_many(docs)
                inserted_count = len(res.inserted_ids)
                logger.info(f"Saved {inserted_count} language health evaluation snapshots to Sync MongoDB.")
            except Exception as e:
                logger.warning(f"Sync Mongo insert error: {e}")

        return inserted_count

    @classmethod
    async def save_model_performance_log(cls, log_entry: Dict[str, Any]) -> bool:
        """Lưu nhật ký đánh giá hiệu năng mô hình (Model Performance Log) vào MongoDB Atlas."""
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        log_copy = dict(log_entry)
        if "timestamp" not in log_copy:
            log_copy["timestamp"] = now_utc.isoformat()

        mongo_client.connect()
        saved = False

        if mongo_client.db is not None:
            try:
                await mongo_client.db["model_performance_logs"].insert_one(log_copy)
                saved = True
                logger.info(f"Saved model performance log to Async MongoDB.")
            except Exception as e:
                logger.warning(f"Async Mongo insert error for performance log: {e}")

        if not saved and mongo_client.sync_db is not None:
            try:
                mongo_client.sync_db["model_performance_logs"].insert_one(log_copy)
                saved = True
                logger.info(f"Saved model performance log to Sync MongoDB.")
            except Exception as e:
                logger.warning(f"Sync Mongo insert error for performance log: {e}")

        return saved

    @classmethod
    async def get_repository_health_history(cls, repo_name: str, limit: int = 30) -> List[Dict[str, Any]]:
        """Truy vấn lịch sử đánh giá điểm sức khỏe của 1 repo để vẽ biểu đồ."""
        history = []
        mongo_client.connect()

        if mongo_client.db is not None:
            try:
                cursor = mongo_client.db["repo_health_evaluations"].find(
                    {"repository": repo_name}
                ).sort("evaluated_at", -1).limit(limit)
                async for doc in cursor:
                    doc["_id"] = str(doc.get("_id"))
                    history.append(doc)
            except Exception as e:
                logger.warning(f"Async Mongo search error: {e}")

        if not history and mongo_client.sync_db is not None:
            try:
                cursor = mongo_client.sync_db["repo_health_evaluations"].find(
                    {"repository": repo_name}
                ).sort("evaluated_at", -1).limit(limit)
                for doc in cursor:
                    doc["_id"] = str(doc.get("_id"))
                    history.append(doc)
            except Exception as e:
                logger.warning(f"Sync Mongo search error: {e}")

        # Re-sort in ascending chronological order for frontend charts
        history.reverse()
        return history

    @classmethod
    async def get_language_health_history(cls, language: str, limit: int = 30) -> List[Dict[str, Any]]:
        """Truy vấn lịch sử điểm sức khỏe & chỉ số của 1 ngôn ngữ lập trình để vẽ biểu đồ."""
        history = []
        mongo_client.connect()

        if mongo_client.db is not None:
            try:
                cursor = mongo_client.db["language_health_evaluations"].find(
                    {"language": language}
                ).sort("evaluated_at", -1).limit(limit)
                async for doc in cursor:
                    doc["_id"] = str(doc.get("_id"))
                    history.append(doc)
            except Exception as e:
                logger.warning(f"Async Mongo search error: {e}")

        if not history and mongo_client.sync_db is not None:
            try:
                cursor = mongo_client.sync_db["language_health_evaluations"].find(
                    {"language": language}
                ).sort("evaluated_at", -1).limit(limit)
                for doc in cursor:
                    doc["_id"] = str(doc.get("_id"))
                    history.append(doc)
            except Exception as e:
                logger.warning(f"Sync Mongo search error: {e}")

        history.reverse()
        return history

    @classmethod
    async def get_aggregated_clean_language_evaluations(
        cls,
        languages: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Truy vấn, loại bỏ dữ liệu không sạch (Unwanted/Markup/Incomplete)
        và nhóm các đánh giá sức khỏe theo ngôn ngữ từ collection 'language_health_evaluations'.
        """
        mongo_client.connect()
        db = mongo_client.db

        unwanted_langs = [
            "Unknown", "", "None", "Jupyter Notebook", "HTML", "CSS",
            "Shell", "Dockerfile", "Makefile", "Batchfile", "TeX",
            "HCL", "Markdown", "Text", "PowerShell"
        ]

        match_stage: Dict[str, Any] = {
            "language": {"$nin": unwanted_langs, "$ne": None, "$exists": True},
            "health_score": {"$gte": 10.0, "$lte": 100.0},
            "repository_count": {"$gte": 3}
        }

        if languages:
            req_set = set()
            for l in languages:
                l_low = l.lower().strip()
                req_set.add(l_low)
                if l_low in ["c#", "csharp", "c sharp", "c%23"]:
                    req_set.add("c#")
                if l_low in ["c++", "cpp", "c plus plus", "c%2b%2b"]:
                    req_set.add("c++")
            escaped_patterns = [f"^{re.escape(x)}$" for x in req_set]
            match_stage["language"] = {
                "$nin": unwanted_langs,
                "$regex": "|".join(escaped_patterns),
                "$options": "i"
            }

        pipeline = [
            {"$match": match_stage},
            {"$sort": {"snapshot_date": 1}},
            {
                "$group": {
                    "_id": "$language",
                    "snapshots": {
                        "$push": {
                            "period_label": "$period_label",
                            "snapshot_date": "$snapshot_date",
                            "health_score": "$health_score",
                            "health_level": "$health_level",
                            "repository_count": "$repository_count",
                            "total_stars": "$total_stars"
                        }
                    },
                    "current_score": {"$last": "$health_score"},
                    "health_level": {"$last": "$health_level"},
                    "repository_count": {"$last": "$repository_count"},
                    "total_stars": {"$last": "$total_stars"},
                    "first_score": {"$first": "$health_score"}
                }
            }
        ]

        results = []
        if db is not None:
            try:
                cursor = db["language_health_evaluations"].aggregate(pipeline)
                async for doc in cursor:
                    results.append(doc)
            except Exception as e:
                logger.warning(f"Error aggregating language_health_evaluations: {e}")

        if not results and mongo_client.sync_db is not None:
            try:
                cursor = mongo_client.sync_db["language_health_evaluations"].aggregate(pipeline)
                for doc in cursor:
                    results.append(doc)
            except Exception as e:
                logger.warning(f"Sync error aggregating language_health_evaluations: {e}")

        cleaned_groups = []
        for doc in results:
            lang_name = doc["_id"]
            snaps = doc.get("snapshots", [])
            if not snaps:
                continue

            pts = [round(float(s["health_score"]), 1) for s in snaps]
            curr_score = round(float(doc.get("current_score", pts[-1])), 1)
            first_score = round(float(doc.get("first_score", pts[0])), 1)
            net_change = round(curr_score - first_score, 1)

            if net_change > 0.5:
                direction = "up"
            elif net_change < -0.5:
                direction = "down"
            else:
                direction = "stable"

            pct_change = round((net_change / max(1.0, first_score)) * 100.0, 1)
            growth_str = f"+{pct_change}%" if pct_change > 0 else (f"{pct_change}%" if pct_change < 0 else "0.0%")

            cleaned_groups.append({
                "language": lang_name,
                "current_score": curr_score,
                "health_level": doc.get("health_level", "HEALTHY"),
                "repository_count": int(doc.get("repository_count", 0)),
                "total_stars": int(doc.get("total_stars", 0)),
                "direction": direction,
                "growth": growth_str,
                "net_change": net_change,
                "points": pts,
                "snapshots": snaps
            })

        cleaned_groups.sort(
            key=lambda x: (x["repository_count"] * 1000 + x["total_stars"]),
            reverse=True
        )
        return cleaned_groups

    @classmethod
    async def get_latest_model_performance_logs(cls, limit: int = 10) -> List[Dict[str, Any]]:
        """Truy vấn các nhật ký hiệu năng & cảnh báo sụt giảm mô hình mới nhất."""
        logs = []
        mongo_client.connect()

        if mongo_client.db is not None:
            try:
                cursor = mongo_client.db["model_performance_logs"].find({}).sort("timestamp", -1).limit(limit)
                async for doc in cursor:
                    doc["_id"] = str(doc.get("_id"))
                    logs.append(doc)
            except Exception as e:
                logger.warning(f"Async Mongo search error: {e}")

        if not logs and mongo_client.sync_db is not None:
            try:
                cursor = mongo_client.sync_db["model_performance_logs"].find({}).sort("timestamp", -1).limit(limit)
                for doc in cursor:
                    doc["_id"] = str(doc.get("_id"))
                    logs.append(doc)
            except Exception as e:
                logger.warning(f"Sync Mongo search error: {e}")

        return logs

