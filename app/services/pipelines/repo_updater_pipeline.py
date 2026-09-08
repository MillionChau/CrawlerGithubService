import os
import json
import logging
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional

from app.db.mongo import mongo_client
from app.core.github_client import github_client
from app.services.data_cleaner import DataCleaner

logger = logging.getLogger(__name__)


class RepoUpdaterPipeline:
    """
    Pipeline chuyên biệt để cập nhật định kỳ các repository đã tồn tại trong CSDL.
    Ưu tiên làm mới các repo có thời gian đồng bộ (last_synced_at) cũ nhất hoặc chưa có.
    """

    async def get_candidate_repositories(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Lấy danh sách các repository cần cập nhật từ MongoDB Atlas hoặc local JSON.
        Ưu tiên các repo chưa có last_synced_at hoặc có last_synced_at cũ nhất.
        """
        candidates = []

        if mongo_client.db is not None:
            try:
                cursor = mongo_client.db["repositories"].find({}).sort("last_synced_at", 1).limit(limit)
                async for doc in cursor:
                    doc["_id"] = str(doc.get("_id"))
                    candidates.append(doc)
                if candidates:
                    logger.info(f"Retrieved {len(candidates)} candidate repos from MongoDB Atlas (Async).")
                    return candidates
            except Exception as e:
                logger.warning(f"Failed to query candidates from Async MongoDB: {e}")

        if not candidates and mongo_client.sync_db is not None:
            try:
                cursor = mongo_client.sync_db["repositories"].find({}).sort("last_synced_at", 1).limit(limit)
                for doc in cursor:
                    doc["_id"] = str(doc.get("_id"))
                    candidates.append(doc)
                if candidates:
                    logger.info(f"Retrieved {len(candidates)} candidate repos from MongoDB Atlas (Sync).")
                    return candidates
            except Exception as e:
                logger.warning(f"Failed to query candidates from Sync MongoDB: {e}")

        # Fallback local JSON
        json_path = "crawled_data.json"
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Sắp xếp repo chưa có last_synced_at lên đầu, sau đó đến repo có timestamp cũ nhất
                    def get_sort_key(item):
                        val = item.get("last_synced_at")
                        return (1, val) if val else (0, "")
                    
                    data.sort(key=get_sort_key)
                    candidates = data[:limit]
                    logger.info(f"Retrieved {len(candidates)} candidate repos from local '{json_path}'.")
            except Exception as e:
                logger.error(f"Error reading {json_path}: {e}")

        return candidates

    async def update_single_repository(self, repo_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Lấy dữ liệu mới nhất từ GitHub API cho 1 repository và cập nhật vào CSDL.
        """
        full_name = repo_info.get("full_name")
        if not full_name and "name" in repo_info and "owner" in repo_info:
            owner_login = repo_info["owner"].get("username") or repo_info["owner"].get("login", "")
            full_name = f"{owner_login}/{repo_info['name']}"

        if not full_name or "/" not in full_name:
            logger.warning(f"Invalid repository full_name: {full_name}. Skipping update.")
            return None

        owner, repo_name = full_name.split("/", 1)
        logger.info(f"🔄 Updating repository data for: {owner}/{repo_name}")

        try:
            # 1. Fetch thông tin repo mới nhất
            raw_repo = await github_client.fetch_repository(owner, repo_name)
            if not raw_repo:
                logger.warning(f"Could not fetch repo details for '{full_name}' from GitHub API.")
                return None

            # 2. Fetch thông tin owner
            clean_user = {}
            try:
                raw_user = await github_client.fetch_user(owner)
                if raw_user:
                    clean_user = DataCleaner.process_user(raw_user)
            except Exception:
                pass

            # 3. Fetch commits mới nhất
            clean_commits = []
            try:
                raw_commits = await github_client.fetch_repo_commits(owner, repo_name, per_page=3)
                clean_commits = [DataCleaner.process_commit(c) for c in raw_commits] if raw_commits else []
            except Exception:
                pass

            # 4. Fetch PRs mới nhất
            clean_prs = []
            try:
                raw_prs = await github_client.fetch_repo_pulls(owner, repo_name, per_page=3)
                clean_prs = [DataCleaner.process_pr(pr) for pr in raw_prs] if raw_prs else []
            except Exception:
                pass

            # 5. Detect frameworks
            frameworks = repo_info.get("detected_frameworks", [])
            try:
                package_json = await github_client.fetch_repo_file_content(owner, repo_name, "package.json")
                req_txt = await github_client.fetch_repo_file_content(owner, repo_name, "requirements.txt")
                detected = DataCleaner.detect_frameworks(package_json, None, req_txt)
                if detected:
                    frameworks = detected
            except Exception:
                pass

            metrics = {
                "commits": clean_commits,
                "pulls": clean_prs,
                "commit_count": len(clean_commits),
                "pr_count": len(clean_prs)
            }

            clean_repo = DataCleaner.process_repo(raw_repo, clean_user, frameworks, metrics)

            # Cập nhật MongoDB Atlas
            if mongo_client.db is not None:
                try:
                    await mongo_client.db["repositories"].update_one(
                        {"id": clean_repo["id"]},
                        {"$set": clean_repo},
                        upsert=True
                    )
                    logger.info(f"✅ Updated '{clean_repo['full_name']}' in MongoDB Atlas ('repositories' collection).")
                except Exception as e:
                    logger.warning(f"Failed to update '{clean_repo['full_name']}' in MongoDB Atlas: {e}")
            elif mongo_client.sync_db is not None:
                try:
                    mongo_client.sync_db["repositories"].update_one(
                        {"id": clean_repo["id"]},
                        {"$set": clean_repo},
                        upsert=True
                    )
                    logger.info(f"✅ Updated '{clean_repo['full_name']}' in MongoDB Atlas (Sync Mode).")
                except Exception as e:
                    logger.warning(f"Failed sync update to MongoDB Atlas: {e}")

            return clean_repo

        except Exception as e:
            logger.error(f"Error while updating repo '{full_name}': {e}", exc_info=True)
            return None

    async def execute(self, batch_size: int = 5) -> Dict[str, Any]:
        """
        Thực thi tiến trình cập nhật định kỳ cho danh sách repository.
        """
        logger.info(f"Starting RepoUpdaterPipeline with batch_size={batch_size}...")
        candidates = await self.get_candidate_repositories(limit=batch_size)

        if not candidates:
            logger.info("No repositories found in database to update.")
            return {
                "status": "success",
                "message": "No repositories to update.",
                "total_candidates": 0,
                "updated_count": 0,
                "failed_count": 0,
                "updated_repos": []
            }

        updated_repos = []
        failed_count = 0

        for candidate in candidates:
            res = await self.update_single_repository(candidate)
            if res:
                updated_repos.append(res)
            else:
                failed_count += 1
            await asyncio.sleep(1)

        # Cập nhật file local crawled_data.json
        if updated_repos:
            try:
                json_path = "crawled_data.json"
                existing_json = []
                if os.path.exists(json_path):
                    with open(json_path, 'r', encoding='utf-8') as f:
                        try:
                            existing_json = json.load(f)
                        except Exception:
                            existing_json = []

                dict_by_id = {str(item["id"]): item for item in existing_json}
                for r in updated_repos:
                    dict_by_id[str(r["id"])] = r

                updated_list = list(dict_by_id.values())
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(updated_list, f, ensure_ascii=False, indent=4)
                logger.info(f"✅ Updated {len(updated_repos)} repos in local 'crawled_data.json'.")
            except Exception as e:
                logger.warning(f"Failed to update local JSON file: {e}")

        summary = {
            "status": "success",
            "total_candidates": len(candidates),
            "updated_count": len(updated_repos),
            "failed_count": failed_count,
            "updated_repos": [r.get("full_name") for r in updated_repos]
        }
        logger.info(f"RepoUpdaterPipeline completed: {summary}")
        return summary
