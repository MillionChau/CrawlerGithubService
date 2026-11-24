import asyncio
import logging
from datetime import datetime, timezone
from pymongo import UpdateOne

from app.db.mongo import mongo_client
from app.core_models.data.db_loader import DatabaseDataLoader
from app.core_models.features.language_features import (
    K_REPO,
    K_STARS,
    UNIVERSAL_STAR_SHARE_MIN,
    UNIVERSAL_STAR_SHARE_MAX,
    UNIVERSAL_REPO_SHARE_MIN,
    UNIVERSAL_REPO_SHARE_MAX,
    UNIVERSAL_CADENCE_CEILING
)
from app.core.crawl_config import CrawlConfigManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("recalibrate_language_health_v3")


async def recalibrate_v3():
    mongo_client.connect()
    db = mongo_client.db
    if db is None:
        logger.error("Could not connect to MongoDB Atlas!")
        return

    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")
    iso_str = now_utc.isoformat()
    period_label = f"T{now_utc.month}"
    snapshot_id = f"SNAP-{today_str}"

    # Clear cache in DatabaseDataLoader to force fresh calculation from Mongo
    DatabaseDataLoader._language_summary_cache = None
    DatabaseDataLoader._language_summary_cache_time = 0.0

    logger.info("Computing Language Health V3 Summary from MongoDB Atlas...")
    summary = await DatabaseDataLoader.get_language_summary()

    if not summary:
        logger.error("No qualified language groups returned from DatabaseDataLoader!")
        return

    logger.info(f"Loaded {len(summary)} languages with Specification V3 metrics.")

    total_repos = sum(s.get("repository_count", 0) for s in summary)
    total_stars = sum(s.get("total_stars", 0) for s in summary)
    total_forks = sum(s.get("total_forks", 0) for s in summary)

    # 1. Lưu bản ghi Provenance & Universal Scale vào crawl_snapshots
    snapshot_doc = {
        "snapshot_id": snapshot_id,
        "snapshot_date": today_str,
        "evaluated_at": iso_str,
        "version": "V3.0-Production",
        "scope": {
            "total_evaluated_repos": total_repos,
            "total_evaluated_stars": total_stars,
            "total_evaluated_forks": total_forks,
            "total_languages_tracked": len(summary)
        },
        "universal_scale": {
            "star_share_min_pct": UNIVERSAL_STAR_SHARE_MIN,
            "star_share_max_pct": UNIVERSAL_STAR_SHARE_MAX,
            "repo_share_min_pct": UNIVERSAL_REPO_SHARE_MIN,
            "repo_share_max_pct": UNIVERSAL_REPO_SHARE_MAX,
            "k_repo": K_REPO,
            "k_stars": K_STARS,
            "cadence_ceiling": UNIVERSAL_CADENCE_CEILING
        },
        "weights": CrawlConfigManager.get_language_health_weights()
    }

    await db["crawl_snapshots"].update_one(
        {"snapshot_id": snapshot_id},
        {"$set": snapshot_doc},
        upsert=True
    )
    logger.info(f"Updated crawl_snapshots with scope: {total_repos:,} repos, {total_stars:,} stars.")

    # 2. Chuẩn bị Bulk Write cho language_health_evaluations
    upsert_ops = []
    print("\n=== ĐÁNH GIÁ SỨC KHỎE NGÔN NGỮ (SPECIFICATION V3) ===")
    print(f"{'Ngôn ngữ':<14} {'Stars':<11} {'Share%':<8} {'Density':<8} {'Popular':<8} {'Flow':<8} {'Growth':<8} {'Health':<8} {'Conf'}")
    print("-" * 92)

    for item in summary:
        lang = item["language"]
        doc_to_save = {
            "language": lang,
            "health_score": item["health_score"],
            "health_level": item["health_level"],
            "confidence_score": item["confidence_score"],
            "confidence_level": item["confidence_level"],
            "growth_status": item["growth_status"],
            "repository_count": item["repository_count"],
            "total_stars": item["total_stars"],
            "total_forks": item["total_forks"],
            "period_label": period_label,
            "snapshot_date": today_str,
            "snapshot_id": snapshot_id,
            "evaluated_at": iso_str,
            "version": "v3_production",
            "stock": item.get("stock", {}),
            "flow": item.get("flow", {}),
            "momentum": item.get("momentum", {}),
            "cohort": item.get("cohort", {}),
            # Backwards compatibility flat metrics
            "metrics": {
                "repo_density_score": item["repo_density_score"],
                "popularity_score": item["popularity_score"],
                "ecosystem_activity_score": item["ecosystem_activity_score"],
                "growth_momentum_score": item["growth_momentum_score"] if item["growth_momentum_score"] is not None else 50.0
            },
            "activity_coverage_pct": item["activity_coverage_pct"],
            "activity_intensity_score": item["activity_intensity_score"],
            "fork_depth_quality": item["fork_depth_quality"],
            "repo_growth_rate": item["repo_growth_rate"],
            "star_growth_rate": item["star_growth_rate"],
            "raw_repo_growth_pct": item["raw_repo_growth_pct"],
            "raw_star_growth_pct": item["raw_star_growth_pct"],
            "composite_raw_momentum_pct": item["composite_raw_momentum_pct"],
            "jaccard_similarity": item["jaccard_similarity"]
        }

        upsert_ops.append(
            UpdateOne(
                {"language": lang, "snapshot_date": today_str},
                {"$set": doc_to_save},
                upsert=True
            )
        )

        if item["repository_count"] >= 100 or item["total_stars"] >= 300000:
            g_str = f"{item['growth_momentum_score']:<8.1f}" if item["growth_momentum_score"] is not None else f"{'None':<8}"
            print(f"{lang:<14} {item['total_stars']:<11} {item['star_market_share_pct']:<8.2f} {item['repo_density_score']:<8.1f} {item['popularity_score']:<8.1f} {item['ecosystem_activity_score']:<8.1f} {g_str} {item['health_score']:<8.2f} {item['confidence_score']}")

    if upsert_ops:
        logger.info(f"Bulk upserting {len(upsert_ops)} snapshots into language_health_evaluations...")
        res = await db["language_health_evaluations"].bulk_write(upsert_ops, ordered=False)
        logger.info(f"Upserted successfully! Matched: {res.matched_count}, Upserted: {len(res.upserted_ids)}")

    logger.info("Recalibration V3 Complete!")


if __name__ == "__main__":
    asyncio.run(recalibrate_v3())
