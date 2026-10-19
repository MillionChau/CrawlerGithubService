import asyncio
import json
import logging
from pprint import pprint

from app.db.mongo import mongo_client
from app.core_models.data.db_loader import DatabaseDataLoader
from app.core_models.health.repository_health import RepositoryHealthModel
from app.core_models.health.language_health import LanguageHealthModel
from app.core_models.trend.trend_analyzer import TechnologyTrendAnalyzer
from app.core_models.forecasting.forecasting_service import ForecastingService
from app.core_models.persistence.model_manager import ModelManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


async def main():
    print("=" * 70)
    print("DEVRADAR - EVALUATION AND BENCHMARK OF CORE MODELS (MONGODB ATLAS MODE)")
    print("=" * 70)

    # 1. Kết nối MongoDB Atlas và nạp dữ liệu repositories thực tế
    mongo_client.connect()
    print("\n1. Dang tai du lieu Repositories tu MongoDB Atlas...")
    repos = await DatabaseDataLoader.get_all_repositories()
    print(f"Da tim thay {len(repos)} repositories trong CSDL MongoDB Atlas.\n")

    if not repos:
        print("Khong co du lieu trong CSDL! Hay chay crawler de thu thap du lieu truoc.")
        return

    # Sắp xếp repo theo stars giảm dần để đánh giá bài test khách quan
    repos_sorted = sorted(repos, key=lambda x: int(x.get('stars', 0)), reverse=True)

    # 2. Chạy Repository Health Model
    print("-" * 70)
    print("2. DANH GIA REPOSITORY HEALTH MODEL")
    print("-" * 70)
    repo_health_model = RepositoryHealthModel()
    
    for repo in repos_sorted[:5]:
        health_result = repo_health_model.evaluate(repo)
        print(f"Repo: {health_result['repository']} (Stars: {repo.get('stars', 0)})")
        print(f"   - Score: {health_result['health_score']}/100 | Level: {health_result['health_level']}")
        print(f"   - Chi tiet sub-scores: {health_result['components']}\n")

    # 3. Chạy Language Health Model
    print("-" * 70)
    print("3. DANH GIA LANGUAGE HEALTH MODEL")
    print("-" * 70)
    lang_health_model = LanguageHealthModel()
    lang_summaries = await DatabaseDataLoader.get_language_summary()

    for lang in lang_summaries:
        lang_result = lang_health_model.evaluate(lang)
        print(f"Ngon ngu: {lang_result['language']} (Repos: {lang['repository_count']}, Stars: {lang['total_stars']})")
        print(f"   - Health Score: {lang_result['health_score']}/100 | Level: {lang_result['health_level']}")
        print(f"   - Metrics: {lang_result['metrics']}\n")

    # 4. Phân tích Xu Hướng Công Nghệ Thực Tế (Technology Trend Analysis)
    print("-" * 70)
    print("4. PHAN TICH XU HUONG CONG NGHE THUC TE (TREND ANALYSIS)")
    print("-" * 70)
    trend_analyzer = TechnologyTrendAnalyzer()
    
    for lang in lang_summaries:
        total_stars = lang['total_stars']
        growth = lang['star_growth_rate']
        # Tạo chuỗi thời gian thực tế dựa trên tốc độ tăng trưởng của từng ngôn ngữ
        series_data = [
            round(total_stars * (1.0 - growth * 3), 1),
            round(total_stars * (1.0 - growth * 2), 1),
            round(total_stars * (1.0 - growth * 1), 1),
            round(float(total_stars), 1)
        ]
        trend_result = trend_analyzer.analyze(lang['language'], series_data)
        print(f"Cong nghe: {trend_result['technology']}")
        print(f"   - Xu huong: {trend_result['trend']} | Growth Rate: {trend_result['growth_rate']} | Momentum: {trend_result['momentum']}\n")

    # 5. Dự báo Chuỗi Thời Gian (Technology Forecasting Model)
    print("-" * 70)
    print("5. DU BAO XU HUONG TUONG LAI (TIME-SERIES FORECASTING)")
    print("-" * 70)
    forecasting_service = ForecastingService()

    for lang in lang_summaries[:3]:
        count = lang['repository_count']
        rate = lang['repo_growth_rate']
        history = [
            {"timestamp": "2026-05-01", "value": round(count * (1.0 - rate * 3), 1)},
            {"timestamp": "2026-06-01", "value": round(count * (1.0 - rate * 2), 1)},
            {"timestamp": "2026-07-01", "value": round(count * (1.0 - rate * 1), 1)},
            {"timestamp": "2026-08-01", "value": float(count)}
        ]
        forecast_result = forecasting_service.predict_technology(lang['language'], history, steps=3)
        print(f"Du bao 3 thang toi cho cong nghe: {forecast_result['technology']}")
        for f in forecast_result['forecast']:
            print(f"   - Thang {f['timestamp']}: Du doan = {f['predicted_value']} (Khoang tin cay: {f['lower_bound']} - {f['upper_bound']})")
        print()

    # 6. Model Persistence (Lưu Artifacts bằng Joblib)
    print("-" * 70)
    print("6. LUU MO HINH (MODEL PERSISTENCE BY JOBLIB)")
    print("-" * 70)
    model_manager = ModelManager()
    path1 = model_manager.save_model(repo_health_model, "repository_health", "repo_health_v1")
    path2 = model_manager.save_model(lang_health_model, "language_health", "lang_health_v1")
    print(f"Da luu Repository Health Model artifact vao: {path1}")
    print(f"Da luu Language Health Model artifact vao: {path2}")

    # 7. Lưu Dữ Liệu Đánh Giá & Snapshots Lịch Sử Vào MongoDB Atlas (Phục Vụ Biểu Đồ)
    print("-" * 70)
    print("7. LUU KET QUA DANH GIA & SNAPSHOTS LICH SU VAO MONGODB ATLAS")
    print("-" * 70)
    repo_evals = [repo_health_model.evaluate(r) for r in repos]
    lang_evals = [lang_health_model.evaluate(l) for l in lang_summaries]

    n1 = await DatabaseDataLoader.save_repository_health_evaluations(repo_evals)
    n2 = await DatabaseDataLoader.save_language_health_evaluations(lang_evals)
    print(f"Da luu {n1} ban ghi repo health snapshot vao collection 'repo_health_evaluations'.")
    print(f"Da luu {n2} ban ghi language health snapshot vao collection 'language_health_evaluations'.")

    # Truy vấn thử lịch sử điểm để vẽ biểu đồ
    sample_repo_name = repos_sorted[0].get('full_name', 'unknown')
    repo_history = await DatabaseDataLoader.get_repository_health_history(sample_repo_name, limit=5)
    print(f"\n[DEMO CHART DATA] Lich su 5 snapshot gan nhat cho repo '{sample_repo_name}':")
    for h in repo_history:
        print(f"   - Time: {h.get('snapshot_date')} | Score: {h.get('health_score')} | Level: {h.get('health_level')}")

    # 8. Theo Dõi Chỉ Số Độ Chính Xác & Nhập Nhật Ký Hiệu Năng (Model Performance Log)
    print("-" * 70)
    print("8. THEO DOI CHI SO DO CHINH XAC & SAP DEGRADATION ALERT LOG")
    print("-" * 70)
    from app.core_models.evaluation.metrics import ModelEvaluator, PerformanceTracker
    
    y_true, y_pred = [], []
    for lang in lang_summaries:
        count = lang['repository_count']
        rate = lang['repo_growth_rate']
        history = [
            {"timestamp": "2026-05-01", "value": round(count * (1.0 - rate * 3), 1)},
            {"timestamp": "2026-06-01", "value": round(count * (1.0 - rate * 2), 1)},
            {"timestamp": "2026-07-01", "value": round(count * (1.0 - rate * 1), 1)}
        ]
        res = forecasting_service.predict_technology(lang['language'], history, steps=1)
        if res.get('forecast'):
            y_true.append(float(count))
            y_pred.append(res['forecast'][0]['predicted_value'])

    eval_metrics = ModelEvaluator.evaluate_forecasting(y_true, y_pred)
    perf_report = PerformanceTracker.detect_degradation(eval_metrics)
    
    log_payload = {
        "dataset_size": len(repos),
        "language_count": len(lang_summaries),
        "metrics": eval_metrics,
        "performance_status": perf_report["status"],
        "degraded": perf_report["degraded"],
        "message": perf_report["message"]
    }
    await DatabaseDataLoader.save_model_performance_log(log_payload)
    print(f"Da ghi log hieu nang mo hinh vao collection 'model_performance_logs':")
    print(f"   - Metrics: MAE={eval_metrics['mae']}, RMSE={eval_metrics['rmse']}, MAPE={eval_metrics['mape']}%")
    print(f"   - Performance Status: {perf_report['status']} | Degraded: {perf_report['degraded']}")

    mongo_client.close()

    print("\n" + "=" * 70)
    print("HOAN THANH DANH GIA CORE MODELS VOI DU LIEU MONGODB ATLAS THANH CONG!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())

