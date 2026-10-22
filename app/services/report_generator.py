import re
import uuid
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from app.clients.ai_client import ai_client
from app.core_models.data.db_loader import DatabaseDataLoader
from app.db.mongo import mongo_client
from app.core.logging import logger


def generate_clean_slug(title: str) -> str:
    """Tạo slug URL an toàn từ tiêu đề bài viết."""
    slug = title.lower()
    # Loại bỏ dấu tiếng Việt cơ bản nếu có
    replacements = {
        'à|á|ạ|ả|ã|â|ầ|ấ|ậ|ẩ|ẫ|ă|ằ|ắ|ặ|ẳ|ẵ': 'a',
        'è|é|ẹ|ẻ|ẽ|ê|ề|ế|ệ|ể|ễ': 'e',
        'ì|í|ị|ỉ|ĩ': 'i',
        'ò|ó|ọ|ỏ|õ|ô|ồ|ố|ộ|ổ|ỗ|ơ|ờ|ớ|ợ|ở|ỡ': 'o',
        'ù|ú|ụ|ủ|ũ|ư|ừ|ứ|ự|ử|ữ': 'u',
        'ỳ|ý|ỵ|ỷ|ỹ': 'y',
        'đ': 'd'
    }
    for regex_p, rep in replacements.items():
        slug = re.sub(regex_p, rep, slug)
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s-]+', '-', slug).strip('-')
    if not slug:
        slug = "tech-report"
    return f"{slug[:50]}-{uuid.uuid4().hex[:6]}"


class TechReportGenerator:
    """
    Service tự động sinh báo cáo phân tích công nghệ (Tech Reports)
    kết hợp UnoRouter LLM (`qwen2.5-coder-32b:free`) và số liệu thống kê thực tế
    từ kho dữ liệu cào GitHub (MongoDB Atlas).
    """

    @classmethod
    async def get_metrics_context(cls, target_tech: Optional[str] = None, category: str = "TREND") -> Dict[str, Any]:
        """
        Trích xuất số liệu thực tế từ dữ liệu GitHub Crawler để nạp vào prompt cho AI.
        """
        repos = await DatabaseDataLoader.get_all_repositories()
        total_repos = len(repos)

        filtered_repos = []
        if target_tech:
            target_lower = target_tech.lower()
            filtered_repos = [
                r for r in repos
                if (r.get("primary_language") or "").lower() == target_lower
                or target_lower in (r.get("name") or "").lower()
                or target_lower in (r.get("description") or "").lower()
                or any(target_lower in (f or "").lower() for f in (r.get("frameworks") or []))
            ]

        # Top 5 repos đại diện
        sample_repos = filtered_repos if filtered_repos else repos
        sorted_repos = sorted(sample_repos, key=lambda x: x.get("stars", 0), reverse=True)[:5]
        top_repo_info = [
            {
                "full_name": r.get("full_name") or r.get("name"),
                "stars": r.get("stars", 0),
                "forks": r.get("forks", 0),
                "language": r.get("primary_language", "Unknown"),
                "description": (r.get("description") or "")[:120]
            }
            for r in sorted_repos
        ]

        # Tính tổng stars, forks của nhóm
        tech_total_stars = sum(r.get("stars", 0) for r in (filtered_repos or sample_repos))
        tech_total_forks = sum(r.get("forks", 0) for r in (filtered_repos or sample_repos))

        return {
            "total_system_repositories": total_repos,
            "target_tech": target_tech or "General",
            "matching_repositories_count": len(filtered_repos) if target_tech else total_repos,
            "total_stars": tech_total_stars,
            "total_forks": tech_total_forks,
            "top_repositories": top_repo_info,
            "category": category,
            "analysis_date": datetime.utcnow().strftime("%Y-%m-%d")
        }

    @classmethod
    async def generate_report(
        cls,
        topic: Optional[str] = None,
        category: str = "TREND",
        target_tech: Optional[str] = None,
        include_live_metrics: bool = True
    ) -> Dict[str, Any]:
        """
        Sinh nội dung bài phân tích công nghệ.
        Nếu có AI Client hoạt động, gửi prompt cho LLM.
        Nếu AI Client lỗi/hết lượt gọi (429), sử dụng Heuristic Fallback Engine với số liệu thực tế.
        """
        category_clean = (category or "TREND").upper()
        if category_clean not in ["TREND", "LANGUAGE", "FRAMEWORK", "DEVOPS"]:
            category_clean = "TREND"

        # Lấy số liệu thực tế
        metrics_context = await cls.get_metrics_context(target_tech=target_tech, category=category_clean)

        default_topic = topic
        if not default_topic:
            if target_tech:
                default_topic = f"Phân tích chuyên sâu hệ sinh thái {target_tech} và xu hướng phát triển năm 2026"
            elif category_clean == "LANGUAGE":
                default_topic = "Bức tranh toàn cảnh các ngôn ngữ lập trình thống trị năm 2026"
            elif category_clean == "FRAMEWORK":
                default_topic = "Xu hướng chuyển dịch kiến trúc Framework và thư viện mã nguồn mở 2026"
            elif category_clean == "DEVOPS":
                default_topic = "Toàn cảnh công cụ DevOps, CI/CD và Cloud Native trong kỷ nguyên AI"
            else:
                default_topic = "Báo cáo xu hướng công nghệ phần mềm và các dự án mã nguồn mở thịnh hành 2026"

        # Thử gọi UnoRouter LLM
        ai_result = None
        if ai_client.is_available():
            try:
                system_prompt = (
                    "Bạn là Trưởng nhóm Phân tích Công nghệ & Chuyên gia Kiến trúc Hệ thống cao cấp của nền tảng DevRadar. "
                    "Nhiệm vụ của bạn là tạo một bài báo cáo phân tích công nghệ (Tech Report) chuyên sâu, có cấu trúc học thuật rõ ràng, "
                    "kết hợp số liệu thống kê thu thập từ kho mã nguồn GitHub và phân tích xu hướng kỹ thuật cho cộng đồng lập trình viên.\n\n"
                    "Yêu cầu định dạng đầu ra:\n"
                    "Trả về kết quả dưới định dạng JSON hợp lệ (không kèm markdown ```json bọc ngoài hoặc chỉ kèm chuỗi JSON chuẩn) với các trường:\n"
                    "{\n"
                    '  "title": "Tiêu đề bài viết ngắn gọn, hấp dẫn, chuyên nghiệp",\n'
                    '  "summary": "Tóm tắt cốt lõi bài viết trong 2-3 câu ngắn gọn",\n'
                    '  "tags": ["tag1", "tag2", "tag3"],\n'
                    '  "content_markdown": "Toàn bộ nội dung bài phân tích viết bằng Markdown đầy đủ (tối thiểu 400-800 từ) gồm các phần: 1. Tổng quan & Động lực phát triển, 2. Phân tích dữ liệu thực tế từ DevRadar Crawler, 3. Đánh giá ưu điểm & Thách thức kỹ thuật, 4. Dự báo xu hướng tương lai & Lời khuyên cho Developers."\n'
                    "}"
                )

                user_prompt = (
                    f"Chủ đề báo cáo: {default_topic}\n"
                    f"Chuyên mục: {category_clean}\n"
                    f"Công nghệ trọng tâm: {target_tech or 'Đa công nghệ'}\n"
                    f"Số liệu thực tế từ hệ thống DevRadar Crawler:\n"
                    f"{json.dumps(metrics_context, ensure_ascii=False, indent=2)}\n\n"
                    "Hãy tạo một bài báo cáo phân tích kỹ thuật hoàn chỉnh và sâu sắc dựa trên các số liệu này."
                )

                response_text = await ai_client.generate_text(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=0.7,
                    max_tokens=2500
                )

                if response_text:
                    clean_text = response_text.strip()
                    if clean_text.startswith("```json"):
                        clean_text = clean_text[7:]
                    if clean_text.startswith("```"):
                        clean_text = clean_text[3:]
                    if clean_text.endswith("```"):
                        clean_text = clean_text[:-3]
                    clean_text = clean_text.strip()

                    # 1. Thử parse JSON chuẩn hoặc JSON strict=False (cho phép ký tự newline không escape)
                    try:
                        parsed = json.loads(clean_text, strict=False)
                        if isinstance(parsed, dict) and "title" in parsed and "content_markdown" in parsed:
                            ai_result = parsed
                    except Exception:
                        pass

                    # 2. Nếu parse thất bại nhưng có tiêu đề Markdown '# ', trích xuất trực tiếp
                    if not ai_result and "# " in clean_text:
                        lines = clean_text.split("\n")
                        extracted_title = default_topic
                        extracted_summary = ""
                        for line in lines:
                            l = line.strip()
                            if l.startswith("# "):
                                extracted_title = l.lstrip("# ").strip()
                                break
                        for line in lines:
                            l = line.strip()
                            if l and not l.startswith("#") and not l.startswith(">") and not l.startswith("-") and not l.startswith("*"):
                                extracted_summary = l[:200]
                                break

                        ai_result = {
                            "title": extracted_title,
                            "summary": extracted_summary or f"Báo cáo phân tích chuyên sâu về {extracted_title}.",
                            "tags": [category_clean.lower(), "trend-2026"],
                            "content_markdown": clean_text
                        }
            except Exception as e:
                logger.warning(f"[ReportGenerator] LLM output parsing failed ({e}). Proceeding to Heuristic Fallback.")

        if ai_result:
            title = ai_result.get("title", default_topic)
            summary = ai_result.get("summary", f"Báo cáo phân tích chuyên sâu về {title} từ dữ liệu mã nguồn mở.")
            content_markdown = ai_result.get("content_markdown", "")
            tags = ai_result.get("tags", [category_clean.lower(), "trend-2026"])
            if target_tech and target_tech.lower() not in [t.lower() for t in tags]:
                tags.append(target_tech.lower())

            return {
                "title": title,
                "summary": summary,
                "content_markdown": content_markdown,
                "category": category_clean,
                "tags": tags,
                "metrics_snapshot": metrics_context,
                "slug": generate_clean_slug(title),
                "ai_generated": True,
                "model_used": ai_client.model
            }

        # Heuristic Fallback Engine khi AI không khả dụng hoặc parse lỗi
        logger.info("[ReportGenerator] Using Heuristic Fallback Engine to generate tech report.")
        return cls._generate_heuristic_report(
            topic=default_topic,
            category=category_clean,
            target_tech=target_tech,
            metrics_context=metrics_context
        )

    @classmethod
    def _generate_heuristic_report(
        cls,
        topic: str,
        category: str,
        target_tech: Optional[str],
        metrics_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Tạo báo cáo phân tích theo mẫu chuẩn định dạng Markdown dựa trên dữ liệu thực tế đã cào.
        """
        title = topic
        tech_label = target_tech or "công nghệ mã nguồn mở"
        matching_count = metrics_context.get("matching_repositories_count", 0)
        total_stars = metrics_context.get("total_stars", 0)
        top_repos = metrics_context.get("top_repositories", [])

        summary = (
            f"Báo cáo phân tích chuyên sâu toàn cảnh hệ sinh thái {tech_label} năm 2026 "
            f"dựa trên tập dữ liệu gồm {matching_count:,} kho mã nguồn với hơn {total_stars:,} lượt gắn sao trên GitHub."
        )

        top_repos_md = ""
        for i, r in enumerate(top_repos, 1):
            top_repos_md += f"{i}. **{r.get('full_name')}** (`{r.get('language')}`): ⭐ {r.get('stars'):,} stars | 🍴 {r.get('forks'):,} forks\n   - *Mô tả:* {r.get('description')}\n"

        if not top_repos_md:
            top_repos_md = "- Không có đủ mẫu repository cụ thể trong lượt quét hiện tại.\n"

        content_markdown = f"""# {title}

> **Tóm tắt:** {summary}  
> **Nguồn dữ liệu:** DevRadar Automated Crawler & Analytics Engine  
> **Thời điểm cập nhật:** {metrics_context.get('analysis_date')}

---

## 1. Tổng quan & Bối cảnh Kỹ thuật

Trong bối cảnh ngành công nghiệp phần mềm năm 2026 chứng kiến sự bùng nổ của trí tuệ nhân tạo và các kiến trúc phân tán microservices, việc theo dõi động thái phát triển của **{tech_label}** mang ý nghĩa chiến lược đối với các kỹ sư và kiến trúc sư giải pháp.

Nền tảng **DevRadar** liên tục thu thập và định lượng hành vi của các cộng đồng lập trình viên trên toàn cầu để cung cấp cái nhìn khách quan, dựa trên dữ liệu định lượng thay vì cảm tính.

---

## 2. Phân tích Dữ liệu Thực tế từ DevRadar Crawler

Theo số liệu đo lường trực tiếp từ cơ sở dữ liệu kho lưu trữ:

- **Tổng số kho mã nguồn đại diện được phân tích:** `{matching_count:,}` repositories
- **Tổng lượng sao (Stargazers) tích lũy:** `{total_stars:,}` ⭐
- **Tổng số lượt phân nhánh (Forks):** `{metrics_context.get('total_forks', 0):,}` 🍴
- **Chuyên mục phân loại:** `{category}`

### Danh sách các kho mã nguồn dẫn đầu về chỉ số tương tác:

{top_repos_md}

Các chỉ số trên minh chứng cho mức độ trưởng thành vượt bậc và tính ổn định cao của cộng đồng lập trình viên tham gia đóng góp mã nguồn.

---

## 3. Đánh giá Ưu điểm & Thách thức Kiến trúc

### Ưu điểm nổi bật:
- **Tốc độ cải tiến và phát hành:** Chu kỳ cập nhật mã nguồn diễn ra thường xuyên, tỷ lệ đóng issue trong vòng 30 ngày đạt mức khả quan.
- **Tính module hóa và tái sử dụng:** Khả năng tích hợp mở rộng với các công cụ CI/CD, Containerization (Docker) và Cloud Native.
- **Tài liệu và cộng đồng:** Lượng đóng góp mã nguồn lớn từ nhiều quốc gia giúp chuẩn hóa các tài liệu và Best Practices.

### Thách thức cần lưu ý:
- **Quản lý phụ thuộc (Dependency Management):** Rủi ro từ các lỗ hổng bảo mật chuỗi cung ứng mã nguồn (Supply Chain Security).
- **Chi phí bảo trì kỹ thuật:** Tốc độ thay đổi nhanh đòi hỏi đội ngũ phát triển phải liên tục cập nhật phiên bản tương thích.

---

## 4. Dự báo Xu hướng & Khuyến nghị Hành động (2026 - 2028)

1. **Chuẩn hóa quy trình kiểm thử tự động:** Tận dụng các mô hình AI/ML để phân tích chất lượng mã nguồn và tối ưu hóa hiệu năng trước khi đưa vào sản xuất.
2. **Ưu tiên kiến trúc linh hoạt:** Kết hợp mô hình Microservices hoặc Event-Driven Architecture để đảm bảo khả năng mở rộng quy mô.
3. **Theo dõi nhịp độ cộng đồng:** Tiếp tục theo dõi các chỉ số sức khỏe kho mã nguồn (Repository Health Score) trên DevRadar để đưa ra quyết định công nghệ chính xác.

---
*Báo cáo được khởi tạo tự động bởi Hệ thống Phân tích DevRadar AI & Crawler Service.*
"""

        tags = [category.lower(), "trend-2026", "analytics"]
        if target_tech:
            tags.append(target_tech.lower())

        return {
            "title": title,
            "summary": summary,
            "content_markdown": content_markdown,
            "category": category,
            "tags": tags,
            "metrics_snapshot": metrics_context,
            "slug": generate_clean_slug(title),
            "ai_generated": False,
            "model_used": "heuristic-engine-v1"
        }


report_generator = TechReportGenerator()
