import os
import json
import uuid
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.db.mongo import mongo_client
from app.core.github_client import github_client
from app.services.data_cleaner import DataCleaner
from app.services.extractors.framework_engine import FrameworkRuleEngine
from app.services.extractors.structure_scanner import StructureScanner
from app.services.analyzers.metrics_calculator import MetricsCalculator

logger = logging.getLogger(__name__)


class CrawlerPipeline:
    def __init__(self):
        self.framework_engine = FrameworkRuleEngine()
        self.structure_scanner = StructureScanner()
        self.metrics_calculator = MetricsCalculator()

    async def execute(
        self,
        query: str = "stars:>10000",
        max_repos: int = 5,
        page: int = 1,
        sort: str = "stars",
        trigger_type: str = "MANUAL",
        session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        session_id = session_id or str(uuid.uuid4())
        started_at = datetime.utcnow()
        logger.info(f"[{session_id}] Executing CrawlerPipeline (MongoDB Mode) with query='{query}', max_repos={max_repos}, page={page}, sort='{sort}', trigger='{trigger_type}'")

        log_entry = {
            "session_id": session_id,
            "started_at": started_at,
            "finished_at": None,
            "duration_seconds": None,
            "trigger_type": trigger_type,
            "query": query,
            "status": "RUNNING",
            "repos_crawled": 0,
            "new_repos_count": 0,
            "updated_repos_count": 0,
            "crawled_repo_names": [],
            "github_rate_limit_remaining": None,
            "error_message": None
        }
        await mongo_client.create_crawl_log(log_entry)
        
        new_repos_count = 0
        updated_repos_count = 0
        crawled_repo_names = []
        results = []

        try:
            raw_repos = await github_client.fetch_repositories(query=query, max_pages=1, page=page, sort=sort)
        except Exception as e:
            logger.error(f"Failed to fetch repositories from GitHub API: {e}")
            finished_at = datetime.utcnow()
            duration = round((finished_at - started_at).total_seconds(), 2)
            await mongo_client.update_crawl_log(session_id, {
                "finished_at": finished_at,
                "duration_seconds": duration,
                "status": "FAILED",
                "error_message": str(e)
            })
            return []

        if not raw_repos:
            logger.warning("No repositories returned from GitHub API.")
            finished_at = datetime.utcnow()
            duration = round((finished_at - started_at).total_seconds(), 2)
            rate_limit_remaining = await github_client.fetch_rate_limit()
            await mongo_client.update_crawl_log(session_id, {
                "finished_at": finished_at,
                "duration_seconds": duration,
                "status": "SUCCESS",
                "repos_crawled": 0,
                "github_rate_limit_remaining": rate_limit_remaining
            })
            return []

        raw_repos = raw_repos[:max_repos]

        # -----------------------------------------------------------------
        # THỬ NGHIỆM 1: Cào dữ liệu cực nhanh bằng GitHub GraphQL API v4 (1 Request)
        # -----------------------------------------------------------------
        try:
            graphql_nodes = await github_client.fetch_repositories_graphql(query=query, max_repos=max_repos)
            if graphql_nodes:
                for node in graphql_nodes:
                    clean_repo = DataCleaner.process_graphql_repo(node)
                    if clean_repo and clean_repo.get("id"):
                        results.append(clean_repo)
                msg = f"[GRAPHQL PIPELINE SUCCESS] Processed {len(results)} repos via GitHub GraphQL API v4 in 1 single HTTP call!"
                print(msg)
                logger.info(msg)
        except Exception as e:
            warn_msg = f"GraphQL pipeline failed: {e}. Falling back to REST API v3..."
            print(warn_msg)
            logger.warning(warn_msg)

        # -----------------------------------------------------------------
        # BƯỚC DỰ PHÒNG (FALLBACK): Cào bằng GitHub REST API v3 (N+1 Requests)
        # -----------------------------------------------------------------
        if not results:
            logger.info("Running REST API v3 fallback pipeline...")
            try:
                raw_repos = await github_client.fetch_repositories(query=query, max_pages=1, page=page, sort=sort)
                owner = repo.get("owner", {}).get("login", "unknown")
                repo_name = repo.get("name", "unknown")
                logger.info(f"Processing repo: {owner}/{repo_name}")

                if raw_user:
                        clean_user = DataCleaner.process_user(raw_user)
            except Exception:
                pass

                clean_commits = []
                try:
                    raw_commits = await github_client.fetch_repo_commits(owner, repo_name, per_page=3)
                    clean_commits = [DataCleaner.process_commit(c) for c in raw_commits] if raw_commits else []
                except Exception:
                    pass

                clean_prs = []
                try:
                    raw_prs = await github_client.fetch_repo_pulls(owner, repo_name, per_page=3)
                    clean_prs = [DataCleaner.process_pr(pr) for pr in raw_prs] if raw_prs else []
                except Exception:
                    pass

                frameworks = []
                try:
                    package_json = await github_client.fetch_repo_file_content(owner, repo_name, "package.json")
                    req_txt = await github_client.fetch_repo_file_content(owner, repo_name, "requirements.txt")
                    frameworks = DataCleaner.detect_frameworks(package_json, None, req_txt)
                except Exception:
                    pass

                metrics = {
                    "commits": clean_commits,
                    "pulls": clean_prs,
                    "commit_count": len(clean_commits),
                    "pr_count": len(clean_prs)
                }

                clean_repo = DataCleaner.process_repo(repo, clean_user, frameworks, metrics)
                results.append(clean_repo)
                crawled_repo_names.append(clean_repo["full_name"])

                # -------------------------------------------------------------
                # Lưu / Upsert dữ liệu duy nhất vào MongoDB Atlas
                # -------------------------------------------------------------
                if mongo_client.db is not None:
                    try:
                        existing = await mongo_client.db["repositories"].find_one({"id": clean_repo["id"]})
                        res = await mongo_client.db["repositories"].update_one(
                            {"id": clean_repo["id"]},
                            {"$set": clean_repo},
                            upsert=True
                        )
                        if existing is None and res.upserted_id:
                            new_repos_count += 1
                            logger.info(f"✨ [NEW REPO] Saved '{clean_repo['full_name']}' into MongoDB Atlas ('repositories' collection).")
                        else:
                            updated_repos_count += 1
                            logger.info(f"🔄 [UPDATED REPO] Updated '{clean_repo['full_name']}' in MongoDB Atlas ('repositories' collection).")
                    except Exception as e:
                        logger.warning(f"Failed to upsert repo '{clean_repo['full_name']}' to MongoDB Atlas: {e}")
                elif mongo_client.sync_db is not None:
                    try:
                        existing = mongo_client.sync_db["repositories"].find_one({"id": clean_repo["id"]})
                        mongo_client.sync_db["repositories"].update_one(
                            {"id": clean_repo["id"]},
                            {"$set": clean_repo},
                            upsert=True
                        )
                        if existing is None:
                            new_repos_count += 1
                            logger.info(f"✨ [NEW REPO] Saved '{clean_repo['full_name']}' into MongoDB Atlas (Sync Mode).")
                        else:
                            updated_repos_count += 1
                            logger.info(f"🔄 [UPDATED REPO] Updated '{clean_repo['full_name']}' in MongoDB Atlas (Sync Mode).")
                    except Exception as e:
                        logger.warning(f"Failed sync upsert to MongoDB Atlas: {e}")
                else:
                    new_repos_count += 1

            except Exception as e:
                logger.error(f"Failed to fetch repositories from GitHub REST API: {e}")
                return []

            if not raw_repos:
                logger.warning("No repositories returned from GitHub REST API.")

            raw_repos = raw_repos[:max_repos]

            for repo in raw_repos:
                try:
                    owner = repo.get("owner", {}).get("login", "unknown")
                    repo_name = repo.get("name", "unknown")
                    logger.info(f"Processing repo via REST: {owner}/{repo_name}")

                    clean_user = {}
                    try:
                        raw_user = await github_client.fetch_user(owner)
                        if raw_user:
                            clean_user = DataCleaner.process_user(raw_user)
                    except Exception:
                        pass

                    clean_commits = []
                    try:
                        raw_commits = await github_client.fetch_repo_commits(owner, repo_name, per_page=3)
                        clean_commits = [DataCleaner.process_commit(c) for c in raw_commits] if raw_commits else []
                    except Exception:
                        pass

                    clean_prs = []
                    try:
                        raw_prs = await github_client.fetch_repo_pulls(owner, repo_name, per_page=3)
                        clean_prs = [DataCleaner.process_pr(pr) for pr in raw_prs] if raw_prs else []
                    except Exception:
                        pass

                    frameworks = []
                    try:
                        package_json = await github_client.fetch_repo_file_content(owner, repo_name, "package.json")
                        req_txt = await github_client.fetch_repo_file_content(owner, repo_name, "requirements.txt")
                        frameworks = DataCleaner.detect_frameworks(package_json, None, req_txt)
                    except Exception:
                        pass

                    metrics = {
                        "commits": clean_commits,
                        "pulls": clean_prs,
                        "commit_count": len(clean_commits),
                        "pr_count": len(clean_prs)
                    }

                    clean_repo = DataCleaner.process_repo(repo, clean_user, frameworks, metrics)
                    results.append(clean_repo)
                except Exception as e:
                    logger.error(f"Error processing REST repo {repo.get('name')}: {e}")

        # -------------------------------------------------------------
        # Lưu / Upsert dữ liệu duy nhất vào MongoDB Atlas
        # -------------------------------------------------------------
        for clean_repo in results:
            if mongo_client.db is not None:
                try:
                    existing = await mongo_client.db["repositories"].find_one({"id": clean_repo["id"]})
                    res = await mongo_client.db["repositories"].update_one(
                        {"id": clean_repo["id"]},
                        {"$set": clean_repo},
                        upsert=True
                    )
                    if existing is None and res.upserted_id:
                        logger.info(f"[NEW REPO] Saved '{clean_repo['full_name']}' into MongoDB Atlas ('repositories' collection).")
                    else:
                        logger.info(f"[UPDATED REPO] Updated '{clean_repo['full_name']}' in MongoDB Atlas ('repositories' collection).")
                except Exception as e:
                    logger.warning(f"Failed to upsert repo '{clean_repo['full_name']}' to MongoDB Atlas: {e}")
            elif mongo_client.sync_db is not None:
                try:
                    existing = mongo_client.sync_db["repositories"].find_one({"id": clean_repo["id"]})
                    mongo_client.sync_db["repositories"].update_one(
                        {"id": clean_repo["id"]},
                        {"$set": clean_repo},
                        upsert=True
                    )
                    if existing is None:
                        logger.info(f"[NEW REPO] Saved '{clean_repo['full_name']}' into MongoDB Atlas (Sync Mode).")
                    else:
                        logger.info(f"[UPDATED REPO] Updated '{clean_repo['full_name']}' in MongoDB Atlas (Sync Mode).")
                except Exception as e:
                    logger.warning(f"Failed sync upsert to MongoDB Atlas: {e}")

        # -------------------------------------------------------------
        # Lưu/Cập nhật file crawled_data.json local (dự phòng)
        # -------------------------------------------------------------
        if results:
            try:
                existing_json = []
                json_path = "crawled_data.json"
                if os.path.exists(json_path):
                    with open(json_path, 'r', encoding='utf-8') as f:
                        try:
                            existing_json = json.load(f)
                        except Exception:
                            existing_json = []
                
                dict_by_id = {str(item["id"]): item for item in existing_json}
                for r in results:
                    dict_by_id[str(r["id"])] = r
                
                updated_list = list(dict_by_id.values())
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(updated_list, f, ensure_ascii=False, indent=4)
                logger.info(f"✅ Saved total {len(updated_list)} repos to local 'crawled_data.json'.")
            except Exception as e:
                logger.warning(f"Failed to save local JSON file: {e}")

        # Cập nhật nhật ký hoàn tất phiên cào (crawl_logs)
        finished_at = datetime.utcnow()
        duration = round((finished_at - started_at).total_seconds(), 2)
        rate_limit_remaining = await github_client.fetch_rate_limit()

        await mongo_client.update_crawl_log(session_id, {
            "finished_at": finished_at,
            "duration_seconds": duration,
            "status": "SUCCESS",
            "repos_crawled": len(results),
            "new_repos_count": new_repos_count,
            "updated_repos_count": updated_repos_count,
            "crawled_repo_names": crawled_repo_names,
            "github_rate_limit_remaining": rate_limit_remaining
        })

        return results
