from app.tasks.risk_analysis import run_risk_analysis


def test_risk_analysis_task_has_stable_celery_name():
    assert run_risk_analysis.name == "app.tasks.risk_analysis.run"
